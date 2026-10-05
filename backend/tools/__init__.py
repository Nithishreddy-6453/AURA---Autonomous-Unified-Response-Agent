from typing import Optional

from backend.tools.base import Tool
from backend.tools.registry import ToolRegistry
from backend.tools.file_search import SearchCompanyFilesTool
from backend.tools.file_read import ReadCompanyFileTool
from backend.tools.document_extract import DocumentExtractTool


def get_default_tool_registry(base_dir: Optional[str] = None) -> ToolRegistry:
    """Creates and returns a central tool registry pre-loaded with standard tools."""
    registry = ToolRegistry()
    registry.register(SearchCompanyFilesTool(base_dir=base_dir))
    registry.register(ReadCompanyFileTool(base_dir=base_dir))
    registry.register(DocumentExtractTool(base_dir=base_dir))
    return registry


__all__ = [
    "Tool",
    "ToolRegistry",
    "SearchCompanyFilesTool",
    "ReadCompanyFileTool",
    "DocumentExtractTool",
    "get_default_tool_registry",
]
