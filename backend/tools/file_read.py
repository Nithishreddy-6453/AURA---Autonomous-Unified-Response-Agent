import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.models.observation import Observation
from backend.tools.base import Tool


class ReadCompanyFileTool(Tool):
    """Tool for reading file contents safely within the company data directory."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.base_dir = (project_root / "data" / "company").resolve()

    @property
    def name(self) -> str:
        return "read_company_file"

    @property
    def description(self) -> str:
        return (
            "Read the content of a company file by its relative path or path returned from file search. "
            "Rejects any paths outside the company data directory."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file inside data/company, e.g. 'invoices/acme_invoice_2026_01.txt'.",
                }
            },
            "required": ["file_path"],
        }

    async def execute(self, **kwargs: Any) -> Observation:
        raw_path = kwargs.get("file_path")
        action_id = kwargs.get("action_id", "")

        if not raw_path:
            return Observation(
                action_id=action_id,
                success=False,
                error="file_path argument is required.",
            )

        candidate_path = Path(raw_path)
        if not candidate_path.is_absolute():
            resolved_path = (self.base_dir / candidate_path).resolve()
        else:
            resolved_path = candidate_path.resolve()

        # Strict security validation: path traversal prevention
        try:
            rel_to_base = resolved_path.relative_to(self.base_dir)
        except ValueError:
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Access denied: Path '{raw_path}' is outside company data directory.",
            )

        if not resolved_path.exists():
            return Observation(
                action_id=action_id,
                success=False,
                error=f"File not found: '{raw_path}'",
            )

        if not resolved_path.is_file():
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Path '{raw_path}' is not a valid file.",
            )

        try:
            stat = resolved_path.stat()
            content = resolved_path.read_text(encoding="utf-8", errors="replace")

            # Check if JSON structure can be provided
            structured_data = None
            if resolved_path.suffix.lower() == ".json":
                try:
                    structured_data = json.loads(content)
                except Exception:
                    pass

            return Observation(
                action_id=action_id,
                success=True,
                result={
                    "file_path": str(rel_to_base).replace("\\", "/"),
                    "filename": resolved_path.name,
                    "size_bytes": stat.st_size,
                    "content": content,
                    "structured_data": structured_data,
                },
            )
        except Exception as e:
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Failed to read file '{raw_path}': {str(e)}",
            )
