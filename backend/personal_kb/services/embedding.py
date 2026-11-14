"""Text embeddings through the OpenAI API, with exponential backoff on rate limits (issue 1.1)."""

from collections.abc import Sequence
from typing import Any

from tenacity.wait import wait_base

from personal_kb.services.openai_retry import call_with_retries, openai_retrying


class EmbeddingService:
    def __init__(
        self, client: Any, *, model: str, dimensions: int, wait: wait_base | None = None, max_attempts: int = 6
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions
        self._retrying = openai_retrying(wait, max_attempts)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in the order of `texts`."""
        if not texts:
            return []
        # no `dimensions` parameter: Ollama and LM Studio do not take it, and text-embedding-3-small gives 1536 anyway
        response = await call_with_retries(
            self._retrying, lambda: self._client.embeddings.create(input=list(texts), model=self._model)
        )
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        for vector in vectors:
            if len(vector) != self._dimensions:
                raise ValueError(
                    f"embedding model {self._model} returned {len(vector)} dimensions, "
                    f"EMBEDDING_DIMENSIONS is {self._dimensions}"
                )
        return vectors
