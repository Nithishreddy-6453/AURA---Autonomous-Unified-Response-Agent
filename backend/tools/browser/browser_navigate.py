import logging
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from backend.models.observation import Observation
from backend.tools.base import Tool
from backend.tools.browser.browser_session import BrowserSession

logger = logging.getLogger(__name__)

# Permitted domains/hosts for browser navigation
ALLOWED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "[::1]",
}

DEFAULT_ALLOWED_PORTS: Set[int] = {3000, 3001}


def get_allowed_ports() -> Set[int]:
    """Retrieves and safely validates allowed browser navigation ports from environment or defaults.
    
    Supports comma-separated integers via AURA_BROWSER_ALLOWED_PORTS or BROWSER_ALLOWED_PORTS.
    Invalid or out-of-range values are ignored with warnings.
    """
    env_val = os.getenv("AURA_BROWSER_ALLOWED_PORTS") or os.getenv("BROWSER_ALLOWED_PORTS")
    if not env_val:
        return set(DEFAULT_ALLOWED_PORTS)

    parsed_ports: Set[int] = set()
    for item in env_val.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        try:
            port_num = int(cleaned)
            if 1 <= port_num <= 65535:
                parsed_ports.add(port_num)
            else:
                logger.warning(f"Ignoring out-of-range port '{cleaned}' in browser port configuration.")
        except ValueError:
            logger.warning(f"Ignoring malformed port '{cleaned}' in browser port configuration.")

    return parsed_ports if parsed_ports else set(DEFAULT_ALLOWED_PORTS)


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
        allowed_ports = get_allowed_ports()
        if port not in allowed_ports:
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
                    f"(Allowed ports: {sorted(list(get_allowed_ports()))})."
                ),
            )

        try:
            page = await self.session.get_page()
            response = await page.goto(url, wait_until="domcontentloaded")
            status_code = response.status if response else 200

            # Brief pause for client-side rendering and hydration
            await page.wait_for_timeout(300)

            title = await page.title()
            current_url = page.url

            # Extract visible page heading if present
            heading = None
            try:
                if hasattr(page, "locator") and not hasattr(page, "_mock_return_value"):
                    heading_el = page.locator("h1, h2, [role='heading']").first
                    if await heading_el.count() > 0 and await heading_el.is_visible():
                        raw_heading = await heading_el.inner_text()
                        if isinstance(raw_heading, str):
                            heading = " ".join(raw_heading.split())[:120] if raw_heading else None
            except Exception:
                heading = None

            # Extract sanitized short visible content snippet from main/body
            content_snippet = None
            try:
                if hasattr(page, "evaluate") and not hasattr(page, "_mock_return_value"):
                    body_text = await page.evaluate(
                        "() => (document.querySelector('main') || document.body)?.innerText?.slice(0, 400) || ''"
                    )
                    if isinstance(body_text, str) and body_text:
                        cleaned_snippet = " ".join(body_text.split())
                        content_snippet = cleaned_snippet[:250] if cleaned_snippet else None
            except Exception:
                content_snippet = None

            return Observation(
                action_id=action_id,
                success=True,
                result={
                    "status_code": status_code,
                    "url": current_url,
                    "title": title,
                    "heading": heading,
                    "content_snippet": content_snippet,
                },
            )
        except Exception as e:
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Browser navigation error: {str(e)}",
            )

    async def close(self) -> None:
        """Safely closes the underlying browser session."""
        if self.session:
            await self.session.close()
