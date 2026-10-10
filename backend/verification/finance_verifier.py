import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

import httpx

from backend.models.task import Task
from backend.verification.verifier import BaseVerifier, VerificationResult

logger = logging.getLogger(__name__)



def parse_source_document(
    file_path: Union[str, Path],
    data_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Independently reads and extracts authoritative fields from a source invoice document.

    Reads directly from the filesystem, guaranteeing that expected values are never
    derived from agent browser typing actions.
    """
    path = Path(file_path)
    resolved: Optional[Path] = None

    if path.is_absolute() and path.exists() and path.is_file():
        resolved = path
    else:
        candidates = []
        if data_dir:
            dd = Path(data_dir).resolve()
            candidates.extend([dd / path, dd / "invoices" / path.name])
        project_root = Path(__file__).resolve().parents[2]
        default_dd = (project_root / "data" / "company").resolve()
        candidates.extend([
            default_dd / path,
            default_dd / "invoices" / path.name,
            default_dd.parent.parent / path,
            path.resolve(),
        ])
        for cand in candidates:
            if cand.exists() and cand.is_file():
                resolved = cand
                break

    if resolved is None:
        raise FileNotFoundError(f"Source invoice document '{file_path}' not found.")

    content = resolved.read_text(encoding="utf-8", errors="replace")
    authoritative: Dict[str, Any] = {"_source_path": str(resolved)}

    for line in content.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip().upper().replace(" ", "_")
        val = val.strip()

        if key in ("INVOICE_NUMBER", "INVOICE_ID", "ID"):
            authoritative["invoice_id"] = val
        elif key in ("VENDOR", "COMPANY", "VENDOR_NAME", "COMPANY_NAME"):
            authoritative["company"] = val
        elif key in ("DATE", "INVOICE_DATE"):
            authoritative["invoice_date"] = val
        elif key in ("DUE_DATE", "PAYMENT_DUE"):
            authoritative["due_date"] = val
        elif key in ("TOTAL_AMOUNT", "AMOUNT", "TOTAL"):
            clean_val = re.sub(r"[^\d.]", "", val)
            if clean_val:
                authoritative["amount"] = clean_val

    return authoritative


class FinanceInvoiceVerifier(BaseVerifier):
    """Independent verifier that checks Finance Portal database records against
    the authoritative source invoice document on disk (ground truth).
    """

    source_name: str = "finance_verifier"

    def __init__(self, base_url: str = "http://localhost:3000", data_dir: Optional[Union[str, Path]] = None):
        self.base_url = base_url
        if data_dir:
            self.data_dir = Path(data_dir).resolve()
        else:
            project_root = Path(__file__).resolve().parents[2]
            self.data_dir = (project_root / "data" / "company").resolve()

    def can_verify(self, task: Task) -> bool:
        """Determines whether this verifier should handle the task.

        Matches if:
        1. Explicit domain is 'finance' (or absent/legacy default), AND
        2. The task metadata specifies a source document/file/reference, OR
        3. The task user goal contains both 'invoice' and 'finance' (case-insensitive).

        Rejects any task whose explicit domain is not 'finance'.
        """
        if not task:
            return False
        meta = task.metadata if isinstance(task.metadata, dict) else {}
        domain = meta.get("domain")
        if domain and str(domain).strip().lower() != "finance":
            return False

        source_ref = (
            meta.get("source_document")
            or meta.get("source_file")
            or meta.get("source_reference")
            or meta.get("source_ref")
        )
        if bool(source_ref):
            return True

        goal = (task.user_goal or "").lower()
        return "invoice" in goal and "finance" in goal


    def parse_source_document(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Independently reads and extracts authoritative fields from a source invoice document."""
        return parse_source_document(file_path, data_dir=self.data_dir)

    async def fetch_portal_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        """Queries the Finance Portal backend independently via REST API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/api/finance/invoices/{invoice_id}", timeout=5.0)
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
        """Resolves source truth from an explicit reference, file path, or task metadata."""
        # 1. Direct dictionary (test mocks or pre-parsed source truth)
        if isinstance(source_reference, dict):
            return dict(source_reference)

        # 2. String or Path pointing to source document
        candidate_path = source_reference or task_metadata.get("source_document") or task_metadata.get("source_file") or task_metadata.get("source_reference")

        if candidate_path and isinstance(candidate_path, (str, Path)):
            try:
                return self.parse_source_document(candidate_path)
            except Exception as e:
                logger.warning(f"[VERIFY] Failed to parse source document '{candidate_path}': {e}")
                return None

        # 3. Fallback: Search data_dir/invoices for any known invoice matching goal or metadata
        inv_dir = self.data_dir / "invoices" if (self.data_dir / "invoices").exists() else self.data_dir
        if inv_dir.exists():
            for f in sorted(inv_dir.glob("*.txt"), reverse=True):
                # Prefer latest acme invoice if mentioned or default
                try:
                    parsed = self.parse_source_document(f)
                    if parsed.get("invoice_id"):
                        return parsed
                except Exception:
                    continue

        return None

    async def verify(
        self,
        task_metadata: Dict[str, Any],
        source_reference: Optional[Union[str, Path, Dict[str, Any]]] = None,
    ) -> VerificationResult:
        """Independently verifies Finance Portal records against authoritative ground truth."""
        source_truth = self.resolve_source_document(task_metadata, source_reference)

        if not source_truth:
            logger.warning("[VERIFY] Missing source document: cannot verify without independent ground truth.")
            return VerificationResult(
                False,
                "Missing source document: cannot verify without independent ground truth.",
            )

        invoice_id = source_truth.get("invoice_id")
        if not invoice_id:
            logger.warning("[VERIFY] Source document does not contain an invoice_id.")
            return VerificationResult(
                False,
                "Source document is missing authoritative invoice_id.",
                expected=source_truth,
            )

        # Query Finance Portal backend independently via REST API
        try:
            actual_data = await self.fetch_portal_invoice(invoice_id)
            if actual_data is None:
                logger.warning(f"[VERIFY] Invoice {invoice_id} not found in Finance Portal.")
                return VerificationResult(
                    False,
                    f"Invoice {invoice_id} not found in Finance Portal.",
                    expected=source_truth,
                )
        except Exception as e:
            logger.error(f"[VERIFY] Error querying Finance Portal for invoice {invoice_id}: {str(e)}")
            return VerificationResult(
                False,
                f"Error querying Finance Portal for invoice {invoice_id}: {str(e)}",
                expected=source_truth,
            )

        # Authoritative comparison
        mismatches = []
        for key in ["company", "invoice_date", "due_date", "amount"]:
            if key in source_truth:
                expected_val = str(source_truth[key]).strip()
                actual_val = str(actual_data.get(key, "")).strip()

                if key == "amount":
                    try:
                        exp_num = float(expected_val)
                        act_num = float(actual_val)
                        if abs(exp_num - act_num) < 0.001:
                            continue
                        else:
                            mismatches.append(f"amount: expected '{expected_val}', got '{actual_val}'")
                            continue
                    except ValueError:
                        pass

                if key == "company":
                    if expected_val.lower() == actual_val.lower():
                        continue

                if expected_val != actual_val:
                    mismatches.append(f"{key}: expected '{expected_val}', got '{actual_val}'")

        if mismatches:
            details = "Verification failed against source truth: " + ", ".join(mismatches)
            logger.warning(
                f"[VERIFY] source={source_truth.get('_source_path', 'source_truth')} "
                f"expected={source_truth} actual={actual_data} mismatch={mismatches}"
            )
            return VerificationResult(
                False,
                details,
                expected=source_truth,
                actual=actual_data,
            )

        logger.info(
            f"[VERIFY] source={source_truth.get('_source_path', 'source_truth')} "
            f"expected={source_truth.get('amount')} actual={actual_data.get('amount')} verified=True"
        )
        return VerificationResult(
            True,
            f"Invoice {invoice_id} successfully verified against independent source truth.",
            expected=source_truth,
            actual=actual_data,
        )


class LegacyFinanceVerifierAdapter(BaseVerifier):
    """Compatibility adapter wrapping legacy or test-double Finance verifiers

    that do not implement can_verify(task). Avoids monkey-patching user-supplied verifiers.
    """

    source_name: str = "finance_verifier"

    def __init__(self, wrapped: Any) -> None:
        self.wrapped = wrapped

    def can_verify(self, task: Task) -> bool:
        if hasattr(self.wrapped, "can_verify") and callable(self.wrapped.can_verify):
            return self.wrapped.can_verify(task)
        if not task:
            return False
        meta = task.metadata if isinstance(task.metadata, dict) else {}
        domain = meta.get("domain")
        if domain and str(domain).strip().lower() != "finance":
            return False

        source_ref = (
            meta.get("source_document")
            or meta.get("source_file")
            or meta.get("source_reference")
            or meta.get("source_ref")
        )
        if bool(source_ref):
            return True
        goal = (task.user_goal or "").lower()
        return "invoice" in goal and "finance" in goal


    async def verify(
        self,
        task_metadata: Dict[str, Any],
        source_reference: Optional[Union[str, Path, Dict[str, Any]]] = None,
    ) -> VerificationResult:
        try:
            return await self.wrapped.verify(task_metadata, source_reference=source_reference)
        except TypeError:
            return await self.wrapped.verify(task_metadata, source_reference)

