"""LLM summaries of older chat messages for SessionMemoryManager (issue 2.1); prompt in prompts/session_summary.yaml.

The summary keeps what the user asked and which specs came up, never what the assistant concluded nor what the
specs say: an answer kept in the summary was taken as fact by later turns, wrong ones included, and qwen3:8b kept
them even when its prompt said not to. So the answers and the tool results reach the summarizer only as the specs
they name; the specs themselves are read again when a later question needs them.
"""

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from tenacity.wait import wait_base

from personal_kb.core.prompts import Prompt
from personal_kb.services.citations import cited_spec_ids
from personal_kb.services.openai_retry import call_with_retries, openai_retrying
from personal_kb.tools.sdd_knowledge import sources_in

_LINK = re.compile(r"\[([^\]\n]+)\]\(([A-Za-z0-9_.-]{1,64})\)")


def _cited(answer: str) -> str:
    titles = {spec_id: title for title, spec_id in _LINK.findall(answer)}
    ids = cited_spec_ids(answer)
    return ", ".join(f"[{titles[i]}]({i})" if i in titles else i for i in ids) or "no spec"


def transcript(messages: Sequence[BaseMessage]) -> str:
    lines = []
    for message in messages:
        if isinstance(message, HumanMessage):
            lines.append(f"user: {message.content}")
        elif isinstance(message, ToolMessage):
            named = sources_in(str(message.content))
            listed = ", ".join(f"{i} «{t}»" if t != i else i for i, t in named.items()) or "no spec"
            lines.append(f"tool result naming {listed}")
        elif isinstance(message, AIMessage):
            for call in message.tool_calls:
                lines.append(f"assistant called {call['name']}({json.dumps(call['args'], ensure_ascii=False)})")
            if message.content:
                lines.append(f"assistant answered, citing {_cited(str(message.content))}")
        elif isinstance(message, SystemMessage):
            lines.append(f"note: {message.content}")
    return "\n".join(lines)


class LlmSummarizer:
    def __init__(
        self,
        client: Any,
        *,
        model: str,
        prompt: Prompt,
        wait: wait_base | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._prompt = prompt
        self._retrying = openai_retrying(wait)
        self._reasoning_effort = reasoning_effort

    async def summarize(self, previous: str | None, messages: Sequence[BaseMessage]) -> str:
        user = self._prompt.render_user(previous_summary=previous or "(none)", transcript=transcript(messages))
        params: dict[str, Any] = {"model": self._model, "temperature": 0}
        if self._reasoning_effort:
            params["reasoning_effort"] = self._reasoning_effort
        completion = await call_with_retries(
            self._retrying,
            lambda: self._client.chat.completions.create(
                messages=[{"role": "system", "content": self._prompt.system}, {"role": "user", "content": user}],
                **params,
            ),
        )
        return (completion.choices[0].message.content or "").strip()
