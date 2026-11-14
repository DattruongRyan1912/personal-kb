"""Model Context Protocol (MCP) server implementation for Personal-KB.

Exposes tools and resources for AI agents (Cursor, Claude Desktop, Antigravity, etc.)
over standard Model Context Protocol. The tools live by concern in spec_tools, memory_tools and governance_tools.
"""

from mcp.server.mcpserver import MCPServer

from personal_kb.mcp.code_tools import register_code_tools
from personal_kb.mcp.context import setup_mcp_context
from personal_kb.mcp.governance_tools import register_governance_tools
from personal_kb.mcp.memory_tools import register_memory_tools
from personal_kb.mcp.spec_tools import register_spec_tools

__all__ = ["create_mcp_server", "get_mcp_server", "setup_mcp_context"]


def create_mcp_server() -> MCPServer:
    """Build and configure the MCPServer instance with tools and resources."""
    server = MCPServer(
        name="personal-kb",
        version="0.1.0",
        instructions="Personal Knowledge Base (Personal-KB) MCP Server for searching and reading system specs.",
    )
    register_spec_tools(server)
    register_memory_tools(server)
    register_governance_tools(server)
    register_code_tools(server)
    return server


_global_mcp_server: MCPServer | None = None


def get_mcp_server() -> MCPServer:
    """Get or create singleton MCPServer instance."""
    global _global_mcp_server
    if _global_mcp_server is None:
        _global_mcp_server = create_mcp_server()
    return _global_mcp_server
