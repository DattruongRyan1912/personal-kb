"""Cross-encoder re-ranking through a Text Embeddings Inference server running BAAI/bge-reranker-v2-m3 (issue 1.4).

The model runs in its own container, so the backend image stays small (issue 4.3). Scores are sigmoid-normalized
to 0.0-1.0 by the server (raw_scores: false).
"""

from collections.abc import Sequence

import httpx

from personal_kb.core.exceptions import DependencyUnavailableError


class TeiReranker:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http  # base_url points at the TEI server

    async def score(self, query: str, texts: Sequence[str]) -> list[float]:
        """One relevance score per text, in the order of `texts`."""
        if not texts:
            return []
        try:
            response = await self._http.post(
                "/rerank", json={"query": query, "texts": list(texts), "raw_scores": False, "truncate": True}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DependencyUnavailableError("reranker", str(exc)) from exc
        scores = [0.0] * len(texts)
        for item in response.json():
            scores[item["index"]] = item["score"]
        return scores
