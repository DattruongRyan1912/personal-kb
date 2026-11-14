"""Run one agent tool by name with JSON arguments, against the real services (issue 2.2; playbook of 4.4).

Usage:  docker compose exec ai-backend python -m scripts.run_tool search_sdd_knowledge '{"query": "API gửi mail"}'
        docker compose exec ai-backend python -m scripts.run_tool --list
A tool never raises: whatever fails comes back as text starting with "Lỗi:".
"""

import argparse
import asyncio
import json

from personal_kb.bootstrap import services
from personal_kb.core.config import get_settings
from personal_kb.tools.registry import ToolRegistry


async def main(name: str, args: dict) -> None:
    registry = ToolRegistry.discover()
    async with services(get_settings()) as built:
        print(await registry.execute(name, args, built.tool_context))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", nargs="?")
    parser.add_argument("args", nargs="?", default="{}", help="JSON object")
    parser.add_argument("--list", action="store_true", help="print the OpenAI schemas of every tool")
    options = parser.parse_args()
    if options.list or not options.name:
        print(json.dumps(ToolRegistry.discover().openai_schemas(), ensure_ascii=False, indent=2))
    else:
        asyncio.run(main(options.name, json.loads(options.args)))
