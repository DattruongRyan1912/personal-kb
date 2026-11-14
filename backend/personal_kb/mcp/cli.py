"""CLI entrypoint for running Personal-KB MCP Server over stdio.

Usage:
    python -m personal_kb.mcp.cli

IMPORTANT:
    All logging is redirected to sys.stderr to maintain strict JSON-RPC protocol
    integrity over sys.stdout. No stdout print calls are permitted.
"""

import asyncio
import logging
import sys

from personal_kb.bootstrap import services
from personal_kb.core.config import get_settings
from personal_kb.mcp.server import get_mcp_server, setup_mcp_context


def main() -> None:
    # 1. Direct all logging to stderr to keep stdout 100% clean for JSON-RPC framing
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [MCP] %(name)s: %(message)s",
    )
    log = logging.getLogger("personal_kb.mcp.cli")
    log.info("Starting Personal-KB MCP Server via stdio transport...")

    settings = get_settings()

    async def _run() -> None:
        async with services(settings) as built:
            setup_mcp_context(built.tool_context)
            server = get_mcp_server()
            log.info(
                "MCP Server initialized with tools: search_knowledge, get_spec_content, list_specs, "
                "verify_citation, recall_guardrails, recall_exemplar, query_cognitive_memory, "
                "propose_knowledge_update, log_progress, get_worklog"
            )
            log.info("Ready for JSON-RPC messages on stdio.")
            await server.run_stdio_async()

    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, SystemExit):
        log.info("MCP server stopped.")
    except Exception as exc:
        log.error("MCP server encountered fatal error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
