"""LLM extraction of graph nodes and edges from one spec chunk (issue 1.3).

A chunk whose output is not valid JSON, breaks the ontology or refers to unlisted nodes is logged and skipped, so one
hallucinated answer never stops a whole ingestion run. A request that still fails after the retries (a timeout, a
model that is down) raises: the caller then applies nothing of that revision, see services/graph_ingestion.py.
"""

import logging
from typing import Any

from tenacity.wait import wait_base

from personal_kb.core.prompts import Prompt
from personal_kb.services.chunking import SpecChunk
from personal_kb.services.graph_models import GraphExtraction, spec_node_id
from personal_kb.services.openai_retry import openai_retrying
from personal_kb.services.structured_output import InvalidModelOutput, structured_completion

log = logging.getLogger(__name__)


class GraphExtractor:
    def __init__(
        self,
        client: Any,
        *,
        model: str,
        prompt: Prompt,
        wait: wait_base | None = None,
        max_attempts: int = 6,
        reasoning_effort: str | None = None,
    ) -> None:
        self._client = client
        self._reasoning_effort = reasoning_effort
        self._model = model
        self._prompt = prompt
        self._retrying = openai_retrying(wait, max_attempts)

    async def extract(self, chunk: SpecChunk) -> GraphExtraction | None:
        user = self._prompt.render_user(
            spec_id=chunk.spec_id,
            spec_node_id=spec_node_id(chunk.spec_id),
            headings=" > ".join(chunk.headings) or "(none)",
            content=chunk.content,
        )
        try:
            return await structured_completion(
                self._client,
                self._retrying,
                model=self._model,
                system=self._prompt.system,
                user=user,
                output_model=GraphExtraction,
                name="graph_extraction",
                reasoning_effort=self._reasoning_effort,
            )
        except InvalidModelOutput as exc:
            log.warning("[GraphExtractor] %s chunk %d skipped: %s", chunk.spec_id, chunk.chunk_index, exc)
            return None
