"""Tool registry (issue 2.2): finds the tools of this package, exposes them as OpenAI function-calling schemas and runs
them by name."""

import importlib
import pkgutil
from collections.abc import Sequence

from langchain_core.tools import StructuredTool

from personal_kb.tools.base import BaseAgentTool, ToolContext

PACKAGE = "personal_kb.tools"


class ToolRegistry:
    def __init__(self, tools: Sequence[BaseAgentTool]) -> None:
        self._tools: dict[str, BaseAgentTool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"two tools are named {tool.name}")
            self._tools[tool.name] = tool

    @classmethod
    def discover(cls, package: str = PACKAGE) -> "ToolRegistry":
        """Import every module of the package and register each concrete BaseAgentTool subclass it defines.
        Instantiating validates them, so a tool with a bad description stops the app at startup."""
        root = importlib.import_module(package)
        for module in pkgutil.iter_modules(root.__path__):
            importlib.import_module(f"{package}.{module.name}")
        classes = [
            c
            for c in _subclasses(BaseAgentTool)
            if c.__module__.startswith(f"{package}.") and c.run is not BaseAgentTool.run
        ]
        return cls([c() for c in sorted(classes, key=lambda c: c.__qualname__)])

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def openai_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_schema.model_json_schema(),
                },
            }
            for tool in self._tools.values()
        ]

    def as_langchain_tools(self, ctx: ToolContext) -> list[StructuredTool]:
        """The tools as LangChain tools, for bind_tools and so LangGraph emits on_tool_start / on_tool_end (3.1).
        They keep the registry's contract: any failure, bad arguments included, comes back as text."""
        return [_as_langchain(tool, ctx) for tool in self._tools.values()]

    def status_text(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        return tool.status_text(args) if tool else f"⚙️ Đang chạy công cụ {name}..."

    async def execute(self, name: str, args: dict, ctx: ToolContext) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Lỗi: không có công cụ tên {name}. Các công cụ hiện có: {', '.join(self._tools)}."
        return await tool.execute(args, ctx)


def _subclasses(cls: type) -> list[type]:
    found = []
    for sub in cls.__subclasses__():
        found += [sub, *_subclasses(sub)]
    return found


def _as_langchain(tool: BaseAgentTool, ctx: ToolContext) -> StructuredTool:
    async def run(**kwargs) -> str:
        return await tool.execute(kwargs, ctx)

    return StructuredTool.from_function(
        coroutine=run,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        handle_validation_error=lambda exc: f"Lỗi: tham số không hợp lệ cho {tool.name}. Hãy gọi lại với tham số đúng.",
    )
