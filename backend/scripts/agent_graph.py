"""Print the agent's LangGraph as Mermaid (issue 2.3: the graph diagram for the pull request).

Usage:  docker compose exec ai-backend python -m scripts.agent_graph
"""

from personal_kb.core.config import get_settings
from personal_kb.core.prompts import load_prompt
from personal_kb.infrastructure.chat_model import build_chat_model
from personal_kb.services.agent import build_agent_graph
from personal_kb.tools.base import ToolContext
from personal_kb.tools.registry import ToolRegistry

if __name__ == "__main__":
    graph = build_agent_graph(
        build_chat_model(get_settings()),
        ToolRegistry.discover(),
        ToolContext(retriever=None, documents=None),
        persona=load_prompt("agent_persona").system,
    )
    print(graph.get_graph().draw_mermaid())
