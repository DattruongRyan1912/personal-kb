"""Search terms for the knowledge graph, extracted from a user's question by the LLM (issue 1.4, task 2).

A failed extraction yields no terms: the search then relies on the vector side only instead of failing.
"""

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict
from tenacity.wait import wait_base

from personal_kb.core.prompts import Prompt
from personal_kb.services.graph_models import to_snake
from personal_kb.services.openai_retry import openai_retrying
from personal_kb.services.structured_output import InvalidModelOutput, structured_completion

log = logging.getLogger(__name__)

MIN_TERM_LENGTH = 2


class QueryTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terms: list[str]


class QueryEntityExtractor:
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
        self._reasoning_effort = reasoning_effort
        self._model = model
        self._prompt = prompt
        self._retrying = openai_retrying(wait, max_attempts)

    async def terms(self, query: str) -> list[str]:
        try:
            output = await structured_completion(
                self._client,
                self._retrying,
                model=self._model,
                system=self._prompt.system,
                user=self._prompt.render_user(query=query),
                output_model=QueryTerms,
                name="query_terms",
                reasoning_effort=self._reasoning_effort,
            )
        except InvalidModelOutput as exc:
            log.warning("[QueryEntityExtractor] no graph terms for the query: %s", exc)
            return []
        normalized = (to_snake(term) for term in output.terms)
        return list(dict.fromkeys(t for t in normalized if len(t) >= MIN_TERM_LENGTH))
