"""Tool Registry.

Central registry for agent tools.
"""

import inspect
import logging
from typing import Optional

from core.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for agent tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            logger.warning(f"[ToolRegistry] Overwriting tool: {tool.name}")
        self._tools[tool.name] = tool
        logger.info(f"[ToolRegistry] Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_all_definitions(self) -> list[dict]:
        return [tool.get_definition() for tool in self._tools.values()]

    async def execute(self, tool_name: str, arguments: dict) -> str:
        tool = self._tools.get(tool_name)
        if not tool:
            available = ", ".join(self._tools.keys())
            return f"Error: Unknown tool '{tool_name}'. Available: {available}"
        try:
            result = tool.ainvoke(**arguments)
            if inspect.isawaitable(result):
                return await result
            return result
        except Exception as e:
            logger.error(f"[ToolRegistry] Tool '{tool_name}' failed: {e}")
            return f"Error executing {tool_name}: {str(e)}"

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
