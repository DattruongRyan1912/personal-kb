"""The ToolContext the MCP tools read (retriever, documents, worklog, projects), set once at startup."""

from personal_kb.tools.base import ToolContext


class _MCPContextHolder:
    def __init__(self) -> None:
        self.ctx: ToolContext | None = None

    def get(self) -> ToolContext:
        if self.ctx is None:
            raise RuntimeError("MCP server ToolContext is not initialized. Call setup_mcp_context(ctx) first.")
        return self.ctx


context_holder = _MCPContextHolder()


def setup_mcp_context(ctx: ToolContext) -> None:
    """Inject runtime ToolContext (retriever, documents) into the MCP server."""
    context_holder.ctx = ctx
