import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.models.observation import Observation
from backend.tools.base import Tool


class SearchCompanyFilesTool(Tool):
    """Tool for searching company files matching queries within safe company directories."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        else:
            # Default to data/company relative to workspace root
            project_root = Path(__file__).resolve().parent.parent.parent
            self.base_dir = (project_root / "data" / "company").resolve()

    @property
    def name(self) -> str:
        return "search_company_files"

    @property
    def description(self) -> str:
        return (
            "Search for files within the company data repository matching natural language keywords. "
            "Returns a list of matching file paths and metadata. Never searches outside company directories."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language keywords to search for, e.g. 'Acme invoice', 'onboarding', 'Globex'.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional subfolder category to narrow down search, e.g. 'invoices', 'customer_requests', 'onboarding'.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> Observation:
        query = str(kwargs.get("query", "")).strip().lower()
        category = kwargs.get("category")
        action_id = kwargs.get("action_id", "")

        if not query:
            return Observation(
                action_id=action_id,
                success=False,
                error="Search query cannot be empty.",
            )

        if not self.base_dir.exists():
            return Observation(
                action_id=action_id,
                success=True,
                result={"matches": [], "count": 0, "message": "Company data directory does not exist."},
            )

        target_dir = self.base_dir
        if category:
            candidate_dir = (self.base_dir / str(category).strip()).resolve()
            try:
                candidate_dir.relative_to(self.base_dir)
                if candidate_dir.exists():
                    target_dir = candidate_dir
            except ValueError:
                return Observation(
                    action_id=action_id,
                    success=False,
                    error=f"Invalid category path traversal attempt: '{category}'",
                )

        keywords = [word for word in query.split() if len(word) > 1]
        matches: List[Dict[str, Any]] = []

        try:
            for file_path in target_dir.rglob("*"):
                if not file_path.is_file():
                    continue

                # Path traversal guard
                resolved_path = file_path.resolve()
                try:
                    rel_path = resolved_path.relative_to(self.base_dir)
                except ValueError:
                    continue

                name_lower = file_path.name.lower()
                rel_path_str = str(rel_path).replace("\\", "/")

                matched_score = 0
                matched_reason = []

                for kw in keywords:
                    if kw in name_lower:
                        matched_score += 2
                        matched_reason.append(f"filename contains '{kw}'")

                # If text file, check partial contents
                if file_path.suffix.lower() in [".txt", ".json", ".md", ".csv", ".yaml", ".yml"]:
                    try:
                        content_sample = file_path.read_text(encoding="utf-8", errors="ignore").lower()
                        for kw in keywords:
                            if kw in content_sample:
                                matched_score += 1
                                if f"content contains '{kw}'" not in matched_reason:
                                    matched_reason.append(f"content contains '{kw}'")
                    except Exception:
                        pass

                if matched_score > 0:
                    stat = file_path.stat()
                    matches.append({
                        "file_path": rel_path_str,
                        "filename": file_path.name,
                        "size_bytes": stat.st_size,
                        "modified_time": stat.st_mtime,
                        "match_score": matched_score,
                        "reasons": matched_reason,
                    })

            # Sort matches by score descending
            matches.sort(key=lambda x: x["match_score"], reverse=True)

            return Observation(
                action_id=action_id,
                success=True,
                result={"matches": matches, "count": len(matches)},
            )
        except Exception as e:
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Error executing file search: {str(e)}",
            )
