"""The specs a question needs, picked by the LLM from the catalog, read whole on the agent's first tool round.

qwen3:8b, told in its prompt to read the relevant specs whole, kept searching step by step instead; given the specs
to read, it answered far better. So the specs are picked here and read by code. A failed selection reads nothing: the
agent then works with what its own tool calls return.
"""

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict
from tenacity.wait import wait_base

from personal_kb.core.prompts import Prompt
from personal_kb.services.openai_retry import openai_retrying
from personal_kb.services.structured_output import InvalidModelOutput, structured_completion

log = logging.getLogger(__name__)


class SpecChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_ids: list[str]


class SpecSelector:
    def __init__(
        self,
        client: Any,
        *,
        model: str,
        prompt: Prompt,
        wait: wait_base | None = None,
        max_attempts: int = 3,
        reasoning_effort: str | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._prompt = prompt
        self._retrying = openai_retrying(wait, max_attempts)
        self._reasoning_effort = reasoning_effort

    async def select(self, question: str, catalog: str, limit: int) -> list[str]:
        try:
            output = await structured_completion(
                self._client,
                self._retrying,
                model=self._model,
                system=self._prompt.system,
                user=self._prompt.render_user(question=question, catalog=catalog, limit=str(limit)),
                output_model=SpecChoice,
                name="spec_choice",
                reasoning_effort=self._reasoning_effort,
            )
        except InvalidModelOutput as exc:
            log.warning("[SpecSelector] no specs selected: %s", exc)
            return []
        return list(dict.fromkeys(i.strip() for i in output.spec_ids if i.strip()))[:limit]
