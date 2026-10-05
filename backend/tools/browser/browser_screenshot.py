import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.models.observation import Observation
from backend.tools.base import Tool
from backend.tools.browser.browser_session import BrowserSession


class BrowserScreenshotTool(Tool):
    """Tool for capturing full-page or viewport screenshots into a controlled evidence directory."""

    def __init__(self, session: Optional[BrowserSession] = None, evidence_dir: Optional[str] = None):
        self.session = session or BrowserSession()
        if evidence_dir:
            self.evidence_dir = Path(evidence_dir).resolve()
        else:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            self.evidence_dir = (project_root / "data" / "evidence").resolve()

        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "browser_screenshot"

    @property
    def description(self) -> str:
        return (
            "Capture a screenshot of the current browser page. Saves image safely into the project "
            "evidence directory and returns the relative path."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Optional identifier or slug for the screenshot (e.g. 'finance_invoices_page').",
                },
                "full_page": {
                    "type": "boolean",
                    "description": "Whether to capture the entire scrollable page (default false).",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> Observation:
        action_id = kwargs.get("action_id", "")
        raw_name = kwargs.get("name", "screenshot")
        full_page = bool(kwargs.get("full_page", False))

        # Sanitize filename to prevent directory traversal
        sanitized_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(raw_name).strip())
        if not sanitized_name:
            sanitized_name = "screenshot"

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{sanitized_name}_{timestamp}.png"
        target_path = (self.evidence_dir / filename).resolve()

        # Strict containment verification
        try:
            target_path.relative_to(self.evidence_dir)
        except ValueError:
            return Observation(
                action_id=action_id,
                success=False,
                error="Path traversal rejected in screenshot filename.",
            )

        try:
            page = await self.session.get_page()
            await page.screenshot(path=str(target_path), full_page=full_page)

            # Project root relative path
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            rel_path = str(target_path.relative_to(project_root)).replace("\\", "/")

            return Observation(
                action_id=action_id,
                success=True,
                result={
                    "evidence_path": rel_path,
                    "filename": filename,
                    "url": page.url,
                    "title": await page.title(),
                },
            )
        except Exception as e:
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Failed to capture screenshot: {str(e)}",
            )
