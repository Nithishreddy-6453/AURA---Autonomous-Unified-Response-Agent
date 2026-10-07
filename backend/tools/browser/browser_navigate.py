from urllib.parse import urlparse
from typing import Any, Dict, List, Optional

from backend.models.observation import Observation
from backend.tools.base import Tool
from backend.tools.browser.browser_session import BrowserSession

from pathlib import Path
import urllib.request

# Permitted domains/hosts for browser navigation
ALLOWED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "[::1]",
}
ALLOWED_PORTS = {3000}


def is_url_allowed(url: str) -> bool:
    """Security check: only permits navigation to explicitly allowed local origins or workspace test files."""
    try:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            raw_path = urllib.request.url2pathname(parsed.path)
            # Normalize drive letter or unix path
            file_path = Path(raw_path).resolve()
            project_root = Path(__file__).resolve().parents[3]
            return file_path.is_relative_to(project_root) and file_path.exists()
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname or hostname.lower() not in ALLOWED_HOSTS:
            return False
        port = parsed.port or (80 if parsed.scheme == "http" else 443)
        if port not in ALLOWED_PORTS and not (parsed.scheme == "http" and port == 3000):
            return False
        return True
    except Exception:
        return False


class BrowserNavigateTool(Tool):
    """Tool for navigating the browser to permitted local application URLs."""

    def __init__(self, session: Optional[BrowserSession] = None):
        self.session = session or BrowserSession()

    @property
    def name(self) -> str:
        return "browser_navigate"

    @property
    def description(self) -> str:
        return (
            "Navigate the browser to an allowed local web page URL (e.g., 'http://localhost:3000/finance'). "
            "Rejects unauthorized external domains."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The destination URL on localhost (e.g. 'http://localhost:3000/finance/invoices').",
                }
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> Observation:
        action_id = kwargs.get("action_id", "")
        url = kwargs.get("url", "").strip()

        if not url:
            return Observation(
                action_id=action_id,
                success=False,
                error="URL argument cannot be empty.",
            )

        if not is_url_allowed(url):
            return Observation(
                action_id=action_id,
                success=False,
                error=(
                    f"Navigation rejected: URL '{url}' is outside permitted local origins "
                    f"(Allowed: http://localhost:3000)."
                ),
            )

        try:
            page = await self.session.get_page()
            response = await page.goto(url, wait_until="domcontentloaded")
            status_code = response.status if response else 200

            title = await page.title()
            current_url = page.url

            return Observation(
                action_id=action_id,
                success=True,
                result={
                    "status_code": status_code,
                    "url": current_url,
                    "title": title,
                },
            )
        except Exception as e:
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Browser navigation error: {str(e)}",
            )
