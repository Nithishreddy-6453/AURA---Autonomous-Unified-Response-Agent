from typing import Optional

from backend.tools.base import Tool
from backend.tools.registry import ToolRegistry
from backend.tools.file_search import SearchCompanyFilesTool
from backend.tools.file_read import ReadCompanyFileTool
from backend.tools.document_extract import DocumentExtractTool
from backend.tools.browser.browser_session import BrowserSession
from backend.tools.browser.browser_navigate import BrowserNavigateTool
from backend.tools.browser.browser_read import BrowserReadTool
from backend.tools.browser.browser_click import BrowserClickTool
from backend.tools.browser.browser_type import BrowserTypeTool
from backend.tools.browser.browser_screenshot import BrowserScreenshotTool


def get_default_tool_registry(
    base_dir: Optional[str] = None,
    browser_session: Optional[BrowserSession] = None,
    include_browser: bool = True,
) -> ToolRegistry:
    """Creates and returns a central tool registry pre-loaded with standard file and browser tools."""
    registry = ToolRegistry()

    # Register file tools
    registry.register(SearchCompanyFilesTool(base_dir=base_dir))
    registry.register(ReadCompanyFileTool(base_dir=base_dir))
    registry.register(DocumentExtractTool(base_dir=base_dir))

    # Register browser tools sharing the same BrowserSession if enabled
    if include_browser:
        session = browser_session or BrowserSession()
        registry.register(BrowserNavigateTool(session=session))
        registry.register(BrowserReadTool(session=session))
        registry.register(BrowserClickTool(session=session))
        registry.register(BrowserTypeTool(session=session))
        registry.register(BrowserScreenshotTool(session=session))

    return registry


__all__ = [
    "Tool",
    "ToolRegistry",
    "SearchCompanyFilesTool",
    "ReadCompanyFileTool",
    "DocumentExtractTool",
    "BrowserSession",
    "BrowserNavigateTool",
    "BrowserReadTool",
    "BrowserClickTool",
    "BrowserTypeTool",
    "BrowserScreenshotTool",
    "get_default_tool_registry",
]
