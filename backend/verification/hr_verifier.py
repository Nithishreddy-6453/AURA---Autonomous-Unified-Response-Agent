"""Independent verifier for HR Onboarding records against authoritative source truth."""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx

from backend.models.task import Task
from backend.verification.verifier import BaseVerifier, VerificationResult

logger = logging.getLogger(__name__)


def parse_source_onboarding_document(
    file_path: Union[str, Path],
    data_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Independently extracts authoritative fields from a source onboarding request document."""
    path = Path(file_path)
    resolved: Optional[Path] = None

    if path.is_absolute() and path.exists() and path.is_file():
        resolved = path
    else:
        candidates = []
        if data_dir:
            dd = Path(data_dir).resolve()
            candidates.extend([dd / path, dd / "onboarding" / path.name])
        project_root = Path(__file__).resolve().parents[2]
        default_dd = (project_root / "data" / "company").resolve()
        candidates.extend([
            default_dd / path,
            default_dd / "onboarding" / path.name,
            default_dd.parent.parent / path,
            path.resolve(),
        ])
        for cand in candidates:
            if cand.exists() and cand.is_file():
                resolved = cand
                break

    if resolved is None:
        raise FileNotFoundError(f"Source onboarding document '{file_path}' not found.")

    content = resolved.read_text(encoding="utf-8", errors="replace")
    authoritative: Dict[str, Any] = {"_source_path": str(resolved)}
    checklist_items: List[str] = []
    in_checklist = False

    for line in content.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue

        if line_stripped.upper().startswith("CHECKLIST:"):
            in_checklist = True
            continue

        if in_checklist and line_stripped.startswith("-"):
            item_raw = line_stripped.lstrip("-").strip()
            if ":" in item_raw:
                item_name = item_raw.split(":", 1)[0].strip()
            else:
                item_name = item_raw
            if item_name:
                checklist_items.append(item_name)
            continue

        if ":" in line_stripped:
            key, val = line_stripped.split(":", 1)
            key = key.strip().upper().replace(" ", "_")
            val = val.strip()

            if key in ("EMPLOYEE_ID", "EMP_ID", "ID"):
                authoritative["employee_id"] = val
            elif key in ("NAME", "EMPLOYEE_NAME", "CANDIDATE_NAME"):
                authoritative["name"] = val
            elif key in ("DEPARTMENT", "DEPT"):
                authoritative["department"] = val
            elif key in ("START_DATE", "DATE"):
                authoritative["start_date"] = val
            elif key in ("ROLE", "TITLE", "POSITION"):
                authoritative["role"] = val
            elif key in ("STATUS",):
                authoritative["status"] = val

    if checklist_items:
        authoritative["checklist"] = checklist_items

    return authoritative


class HROnboardingVerifier(BaseVerifier):
    """Independent verifier that checks HR Portal records against authoritative ground truth."""

    source_name: str = "hr_verifier"

    def __init__(
        self,
        base_url: str = "http://localhost:3002",
        data_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        self.base_url = base_url
        if data_dir:
            self.data_dir = Path(data_dir).resolve()
        else:
            project_root = Path(__file__).resolve().parents[2]
            self.data_dir = (project_root / "data" / "company").resolve()

    def can_verify(self, task: Task) -> bool:
        """Determines whether this verifier should handle the task.

        Matches if:
        1. Task metadata explicitly specifies domain == 'hr', OR
        2. Task user goal contains both 'hr' and 'onboarding' (case-insensitive) and domain is not 'finance'.
        """
        if not task:
            return False
        meta = task.metadata if isinstance(task.metadata, dict) else {}
        domain = meta.get("domain")
        if domain:
            return domain.lower() == "hr"

        goal = (task.user_goal or "").lower()
        return "hr" in goal and "onboarding" in goal

    def parse_source_document(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Independently extracts authoritative fields from a source onboarding document."""
        return parse_source_onboarding_document(file_path, data_dir=self.data_dir)

    async def fetch_portal_onboarding(self, employee_id: str) -> Optional[Dict[str, Any]]:
        """Queries the HR Sandbox REST API independently."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/hr/onboarding/{employee_id}",
                timeout=5.0,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            json_resp = response.json()
            return json_resp.get("data", {}) if isinstance(json_resp, dict) and "data" in json_resp else json_resp

    def resolve_source_document(
        self,
        task_metadata: Dict[str, Any],
        source_reference: Optional[Union[str, Path, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolves source truth from direct dict, file path, or task metadata."""
        if isinstance(source_reference, dict):
            return dict(source_reference)

        candidate_path = (
            source_reference
            or task_metadata.get("source_document")
            or task_metadata.get("source_file")
            or task_metadata.get("source_reference")
        )

        if candidate_path and isinstance(candidate_path, (str, Path)):
            try:
                return self.parse_source_document(candidate_path)
            except Exception as e:
                logger.warning(f"[VERIFY-HR] Failed to parse source document '{candidate_path}': {e}")
                return None

        # Fallback: scan onboarding directory
        onb_dir = self.data_dir / "onboarding" if (self.data_dir / "onboarding").exists() else self.data_dir
        if onb_dir.exists():
            for f in sorted(onb_dir.glob("*.txt"), reverse=True):
                try:
                    parsed = self.parse_source_document(f)
                    if parsed.get("employee_id"):
                        return parsed
                except Exception:
                    continue

        return None

    async def verify(
        self,
        task_metadata: Dict[str, Any],
        source_reference: Optional[Union[str, Path, Dict[str, Any]]] = None,
    ) -> VerificationResult:
        """Independently verifies HR Portal state against authoritative ground truth."""
        source_truth = self.resolve_source_document(task_metadata, source_reference)

        if not source_truth:
            logger.warning("[VERIFY-HR] Missing source document: cannot verify without independent ground truth.")
            return VerificationResult(
                False,
                "Missing source document: cannot verify without independent ground truth.",
            )

        employee_id = source_truth.get("employee_id")
        if not employee_id:
            logger.warning("[VERIFY-HR] Source document does not contain an employee_id.")
            return VerificationResult(
                False,
                "Source document is missing authoritative employee_id.",
                expected=source_truth,
            )

        try:
            actual_data = await self.fetch_portal_onboarding(employee_id)
            if actual_data is None:
                logger.warning(f"[VERIFY-HR] Onboarding record '{employee_id}' not found in HR Portal.")
                return VerificationResult(
                    False,
                    f"Onboarding record '{employee_id}' not found in HR Portal.",
                    expected=source_truth,
                )
        except Exception as e:
            logger.error(f"[VERIFY-HR] Error querying HR Portal for '{employee_id}': {e}")
            return VerificationResult(
                False,
                f"Error querying HR Portal for '{employee_id}': {e}",
                expected=source_truth,
            )

        # Authoritative field comparison
        mismatches: List[str] = []
        for key in ["name", "department", "start_date"]:
            if key in source_truth:
                expected_val = str(source_truth[key]).strip().lower()
                actual_val = str(actual_data.get(key, "")).strip().lower()
                if expected_val != actual_val:
                    mismatches.append(f"{key}: expected '{source_truth[key]}', got '{actual_data.get(key)}'")

        # Status must be COMPLETED
        actual_status = str(actual_data.get("status", "")).strip().upper()
        if actual_status != "COMPLETED":
            mismatches.append(f"status: expected 'COMPLETED', got '{actual_status}'")

        # Required checklist items check
        expected_checklist = source_truth.get("checklist")
        if expected_checklist and isinstance(expected_checklist, list):
            actual_checklist = actual_data.get("checklist", [])
            if not isinstance(actual_checklist, list):
                mismatches.append(f"checklist: expected list, got {type(actual_checklist).__name__}")
            else:
                actual_checklist_norm = [str(item).strip().lower() for item in actual_checklist]
                for item in expected_checklist:
                    if str(item).strip().lower() not in actual_checklist_norm:
                        mismatches.append(f"checklist missing item: '{item}'")

        if mismatches:
            details = "HR Verification failed against source truth: " + ", ".join(mismatches)
            logger.warning(f"[VERIFY-HR] mismatch={mismatches}")
            return VerificationResult(
                False,
                details,
                expected=source_truth,
                actual=actual_data,
            )

        logger.info(f"[VERIFY-HR] Employee '{employee_id}' successfully verified.")
        return VerificationResult(
            True,
            f"Onboarding record '{employee_id}' successfully verified against independent source truth.",
            expected=source_truth,
            actual=actual_data,
        )
