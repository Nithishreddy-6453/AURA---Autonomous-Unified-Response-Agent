import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.models.observation import Observation
from backend.tools.base import Tool


class DocumentExtractTool(Tool):
    """Tool for parsing and extracting structured key-value entities from documents.

    Supports text, markdown, key-value configurations, and designed to be extensible
    for binary/PDF parsers when libraries are added.
    """

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.base_dir = (project_root / "data" / "company").resolve()

    @property
    def name(self) -> str:
        return "document_extract"

    @property
    def description(self) -> str:
        return (
            "Extract structured fields (e.g. invoice numbers, dates, amounts, line items, keys) "
            "from document text or file paths within company data. Cleanly parses key entities without invoking LLMs."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Optional relative path of the file to extract from.",
                },
                "content": {
                    "type": "string",
                    "description": "Optional raw text content to extract from directly if already read.",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> Observation:
        action_id = kwargs.get("action_id", "")
        file_path_str = kwargs.get("file_path")
        raw_text = kwargs.get("content")

        if not file_path_str and not raw_text:
            return Observation(
                action_id=action_id,
                success=False,
                error="Either 'file_path' or 'content' must be supplied to document_extract.",
            )

        # If file_path provided, read safely within company data directory
        if file_path_str:
            target_path = Path(file_path_str)
            if not target_path.is_absolute():
                resolved = (self.base_dir / target_path).resolve()
            else:
                resolved = target_path.resolve()

            try:
                resolved.relative_to(self.base_dir)
            except ValueError:
                return Observation(
                    action_id=action_id,
                    success=False,
                    error=f"Access denied: Path '{file_path_str}' is outside company data directory.",
                )

            if not resolved.exists():
                return Observation(
                    action_id=action_id,
                    success=False,
                    error=f"File not found: '{file_path_str}'",
                )

            # Handler dispatch for future extensions (e.g., .pdf)
            if resolved.suffix.lower() == ".pdf":
                raw_text = self._extract_pdf(resolved)
            else:
                try:
                    raw_text = resolved.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    return Observation(
                        action_id=action_id,
                        success=False,
                        error=f"Failed to read file for extraction: {str(e)}",
                    )

        if not raw_text:
            return Observation(
                action_id=action_id,
                success=True,
                result={"extracted_fields": {}, "text_length": 0},
            )

        extracted = self._extract_key_values(raw_text)

        return Observation(
            action_id=action_id,
            success=True,
            result={
                "extracted_fields": extracted,
                "text_length": len(raw_text),
            },
        )

    def _extract_pdf(self, path: Path) -> str:
        """Extensible hook for PDF extraction."""
        # When pypdf/pdfminer is installed in future phases, hook here cleanly
        return f"[PDF Placeholder content for {path.name}]"

    def _extract_key_values(self, text: str) -> Dict[str, Any]:
        """Extract structured key-value pairs, dates, amounts, and common document fields."""
        fields: Dict[str, Any] = {}

        # 1. Parse KEY: VALUE lines
        kv_regex = re.compile(r"^([A-Za-z0-9_\-\s]+?)\s*:\s*(.+)$", re.MULTILINE)
        for match in kv_regex.finditer(text):
            k = match.group(1).strip().lower().replace(" ", "_")
            v = match.group(2).strip()
            # Clean numeric values if applicable
            if re.match(r"^-?\d+(\.\d+)?$", v):
                fields[k] = float(v) if "." in v else int(v)
            else:
                fields[k] = v

        # 2. Extract standard financial amount patterns if not captured by key-value
        if "total_amount" not in fields and "amount" not in fields:
            amount_match = re.search(r"(?:total|amount|due)[:\s]+\$?([0-9,]+(?:\.[0-9]{2})?)", text, re.IGNORECASE)
            if amount_match:
                try:
                    fields["detected_amount"] = float(amount_match.group(1).replace(",", ""))
                except ValueError:
                    pass

        # 3. Extract dates if not explicitly mapped
        date_matches = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if date_matches:
            fields["all_dates"] = date_matches
            if "date" not in fields:
                fields["date"] = date_matches[0]

        return fields
