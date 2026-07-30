from typing import Dict
from tools.base.tool import BaseTool


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self):
        return sorted(self._tools.keys())


# Global registry instance
TOOL_REGISTRY = ToolRegistry()