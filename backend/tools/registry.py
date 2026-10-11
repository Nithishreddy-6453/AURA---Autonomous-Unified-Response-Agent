import asyncio
from typing import Any, Dict, List
from backend.tools.base import Tool


class ToolRegistry:
    """Registry maintaining available tools.

    Ensures unknown tool names are rejected and provides specifications
    for planner and execution layers.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance."""
        if not isinstance(tool, Tool):
            raise TypeError(f"Expected Tool instance, got {type(tool).__name__}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """Retrieve a tool by name or raise KeyError if unknown."""
        if name not in self._tools:
            raise KeyError(f"Unknown tool: '{name}'. Available tools: {list(self._tools.keys())}")
        return self._tools[name]

    def list_tools(self) -> List[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def has(self, name: str) -> bool:
        """Check whether a tool with the given name is registered."""
        return name in self._tools

    def get_tool_specs(self) -> List[Dict]:
        """Return tool specifications formatted for prompt/LLM context."""
        specs = []
        for tool in self._tools.values():
            specs.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            })
        return specs

    def get_browser_sessions(self) -> List[Any]:
        """Returns all distinct BrowserSession instances held by registered tools."""
        sessions = []
        for tool in self._tools.values():
            session = getattr(tool, "session", None)
            if session is not None and hasattr(session, "close"):
                if session not in sessions:
                    sessions.append(session)
        return sessions

    async def close(self) -> None:
        """Closes all active resources managed by registered tools."""
        for session in self.get_browser_sessions():
            try:
                res = session.close()
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass
        for tool in self._tools.values():
            if hasattr(tool, "close") and callable(tool.close):
                try:
                    res = tool.close()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass
