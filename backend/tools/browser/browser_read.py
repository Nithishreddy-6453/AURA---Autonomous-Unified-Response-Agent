from typing import Any, Dict, List, Optional
from backend.models.observation import Observation
from backend.tools.base import Tool
from backend.tools.browser.browser_session import BrowserSession


class BrowserReadTool(Tool):
    """Tool for reading structured page information, titles, texts, and interactive elements."""

    def __init__(self, session: Optional[BrowserSession] = None):
        self.session = session or BrowserSession()

    @property
    def name(self) -> str:
        return "browser_read"

    @property
    def description(self) -> str:
        return (
            "Read current browser page state, returning current URL, page title, visible text summary, "
            "and available interactive controls (buttons, links, inputs). Does not return massive raw HTML."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_elements": {
                    "type": "integer",
                    "description": "Maximum number of interactive controls to summarize (default 30).",
                }
            },
        }

    async def execute(self, **kwargs: Any) -> Observation:
        action_id = kwargs.get("action_id", "")
        max_elements = kwargs.get("max_elements", 30)

        try:
            page = await self.session.get_page()
            current_url = page.url
            title = await page.title()

            # Extract structured text and interactive elements via lightweight script evaluation
            extract_script = """
            () => {
                // Collect headings and paragraphs for visible text summary
                const textNodes = [];
                const headings = document.querySelectorAll('h1, h2, h3, p, [role="alert"], table');
                headings.forEach(el => {
                    const text = el.innerText ? el.innerText.trim() : '';
                    if (text && text.length > 0 && text.length < 500) {
                        textNodes.push(text);
                    }
                });

                // Collect key interactive elements
                const interactive = [];
                const elements = document.querySelectorAll('button, a, input, select, textarea');
                elements.forEach(el => {
                    const rect = el.getBoundingClientRect();
                    const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
                    if (!isVisible) return;

                    const tag = el.tagName.toLowerCase();
                    const id = el.id || null;
                    const name = el.getAttribute('name') || null;
                    const type = el.getAttribute('type') || null;
                    const text = (el.innerText || el.value || el.getAttribute('placeholder') || el.getAttribute('aria-label') || '').trim();
                    const role = el.getAttribute('role') || tag;

                    interactive.push({
                        tag,
                        id,
                        name,
                        type,
                        text: text.slice(0, 80),
                        role
                    });
                });

                return {
                    visible_text: textNodes.slice(0, 25).join('\\n'),
                    interactive_elements: interactive
                };
            }
            """

            extracted = await page.evaluate(extract_script)

            return Observation(
                action_id=action_id,
                success=True,
                result={
                    "url": current_url,
                    "title": title,
                    "visible_text_summary": extracted.get("visible_text", ""),
                    "interactive_controls": extracted.get("interactive_elements", [])[:max_elements],
                },
            )
        except Exception as e:
            return Observation(
                action_id=action_id,
                success=False,
                error=f"Error reading page state: {str(e)}",
            )
