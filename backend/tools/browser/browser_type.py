from typing import Any, Dict, Optional
from backend.models.observation import Observation
from backend.tools.base import Tool
from backend.tools.browser.browser_session import BrowserSession


class BrowserTypeTool(Tool):
    """Tool for typing values into web input fields.

    Finds inputs by label, placeholder, name, ID, or CSS selector, clears and types text.
    """

    def __init__(self, session: Optional[BrowserSession] = None):
        self.session = session or BrowserSession()

    @property
    def name(self) -> str:
        return "browser_type"

    @property
    def description(self) -> str:
        return (
            "Type text into an input field identified by label, placeholder, name, ID, or selector. "
            "Clears existing value and fills new content."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to type into the input field.",
                },
                "target": {
                    "type": "string",
                    "description": "Identifier for the target field (e.g. 'invoice_id', 'amount', 'Company / Vendor Name', or '#invoice-search-input').",
                },
                "selector": {
                    "type": "string",
                    "description": "Optional direct CSS selector fallback.",
                },
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> Observation:
        action_id = kwargs.get("action_id", "")
        text = str(kwargs.get("text", ""))
        target = kwargs.get("target", "").strip()
        selector = kwargs.get("selector", "").strip()

        if not target and not selector:
            return Observation(
                action_id=action_id,
                success=False,
                error="Must specify 'target' (e.g. field name/label) or 'selector'.",
            )

        try:
            page = await self.session.get_page()

            locator = None
            strategy = ""

            # Try by direct selector first if explicit
            if selector:
                locator = page.locator(selector).first
                strategy = f"selector='{selector}'"
            elif target:
                # 1. Try if target is an ID or selector format
                if target.startswith("#") or target.startswith("["):
                    locator = page.locator(target).first
                    strategy = f"selector='{target}'"
                # 2. Try by label
                elif await page.get_by_label(target, exact=False).count() > 0:
                    locator = page.get_by_label(target, exact=False).first
                    strategy = f"label='{target}'"
                # 3. Try by placeholder
                elif await page.get_by_placeholder(target, exact=False).count() > 0:
                    locator = page.get_by_placeholder(target, exact=False).first
                    strategy = f"placeholder='{target}'"
                # 4. Try input[name=target] or input[id=target]
                else:
                    locator = page.locator(f"input[name='{target}'], input[id='{target}'], textarea[name='{target}']").first
                    strategy = f"name_or_id='{target}'"

            if locator is None:
                return Observation(
                    action_id=action_id,
                    success=False,
                    error=f"Could not find input element for target '{target or selector}'.",
                )

            await locator.wait_for(state="visible", timeout=7000)
            await locator.fill(text)

            return Observation(
                action_id=action_id,
                success=True,
                result={
                    "action": "typed",
                    "strategy": strategy,
                    "target": target or selector,
                    "length": len(text),
                },
            )
        except Exception as e:
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Failed to type into target '{target or selector}': {str(e)}",
            )
