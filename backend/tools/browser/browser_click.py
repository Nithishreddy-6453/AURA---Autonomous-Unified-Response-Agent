from typing import Any, Dict, Optional
from backend.models.observation import Observation
from backend.tools.base import Tool
from backend.tools.browser.browser_session import BrowserSession


class BrowserClickTool(Tool):
    """Tool for clicking an interactive element using robust locator strategies.

    Supports accessible role/name, text, and CSS selector as fallback.
    """

    def __init__(self, session: Optional[BrowserSession] = None):
        self.session = session or BrowserSession()

    @property
    def name(self) -> str:
        return "browser_click"

    @property
    def description(self) -> str:
        return (
            "Click on an element on the current page using role/name, text match, or CSS selector. "
            "Returns updated URL and observation result."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Visible text or button label to click (e.g. 'View Invoices', 'Save Invoice', '+ New Invoice').",
                },
                "role": {
                    "type": "string",
                    "description": "Accessible role (e.g. 'button', 'link').",
                },
                "selector": {
                    "type": "string",
                    "description": "Fallback CSS selector (e.g. '#submit-invoice-button', 'button[type=submit]').",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> Observation:
        action_id = kwargs.get("action_id", "")
        text = kwargs.get("text")
        role = kwargs.get("role")
        selector = kwargs.get("selector")

        if not text and not selector and not role:
            return Observation(
                action_id=action_id,
                success=False,
                error="Must specify at least 'text', 'role', or 'selector' to click.",
            )

        try:
            page = await self.session.get_page()

            locator = None
            strategy = ""

            # 1. Try Accessible Role + Text if role provided
            if role and text:
                locator = page.get_by_role(role, name=text).first
                strategy = f"role='{role}', name='{text}'"
            # 2. Try Accessible Role alone if specified
            elif role:
                locator = page.get_by_role(role).first
                strategy = f"role='{role}'"
            # 3. Try Text Match
            elif text:
                locator = page.get_by_text(text, exact=False).first
                strategy = f"text='{text}'"
            # 4. Fallback to CSS selector
            elif selector:
                locator = page.locator(selector).first
                strategy = f"selector='{selector}'"

            if locator is None:
                return Observation(
                    action_id=action_id,
                    success=False,
                    error="Unable to construct locator strategy.",
                )

            # Wait for element to be visible and click
            await locator.wait_for(state="visible", timeout=7000)
            await locator.click()

            # Brief pause for DOM/navigation updates
            await page.wait_for_timeout(500)

            current_url = page.url
            title = await page.title()

            return Observation(
                action_id=action_id,
                success=True,
                result={
                    "action": "clicked",
                    "strategy": strategy,
                    "url": current_url,
                    "title": title,
                },
            )
        except Exception as e:
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Failed to click element: {str(e)}",
            )
