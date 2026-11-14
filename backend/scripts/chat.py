"""Ask the agent from the terminal (issues 2.3, 2.4): same services, memory and tools as the API.

Usage:  docker compose exec ai-backend python -m scripts.chat [--session ID] [--user ID] "câu hỏi"
The log traces the graph: "[Agent] Agent_Thinking -> Tool_Executor: …", "[Agent] Tool_Executor ran …", "-> END".
"""

import argparse
import asyncio
import logging
import uuid

from personal_kb.bootstrap import build_chat_agent, services
from personal_kb.core.config import get_settings
from personal_kb.core.prompts import load_prompt
from personal_kb.tools.registry import ToolRegistry


async def main(user_id: str, session_id: str, question: str) -> None:
    settings = get_settings()
    async with services(settings) as built:
        agent = build_chat_agent(built, settings, ToolRegistry.discover(), load_prompt("agent_persona").system)
        answer = await agent.ask(user_id, session_id, question, built.tool_context)
    print(f"\n[session {session_id}]\n{answer.content}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("personal_kb").setLevel(logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--session", default=f"cli-{uuid.uuid4().hex[:8]}")
    parser.add_argument("--user", default="cli-user")
    options = parser.parse_args()
    asyncio.run(main(options.user, options.session, options.question))
