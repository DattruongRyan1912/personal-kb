"""Hybrid retrieval: semantic (vector store) and relational (graph) memory, re-ranked by a cross-encoder (issue 1.4).

The two sides run concurrently: embed the query -> top chunks from the vector store, and LLM terms -> one-hop
neighborhoods from the graph (Postgres; off with GRAPH_SEARCH=false). Their texts are de-duplicated,
scored together, and the best few above a threshold are returned with the spec ids a citation needs.
"""

import asyncio
import hashlib
import json
import logging
import time
import unicodedata
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol, TypeVar

import openai
from pydantic import BaseModel

from personal_kb.core.exceptions import DependencyUnavailableError
from personal_kb.services.graph_text import GraphFact
from personal_kb.services.memory_ports import VectorStore

log = logging.getLogger(__name__)

SEMANTIC_LIMIT = 15
GRAPH_LIMIT = 10
TOP_K = 5
# bge-reranker-v2-m3 scores short or unaccented questions ~0.02 on the right chunk and ~0.001 off topic: 0.3 dropped
# every hit of them; 0.01 kept the right ones and still empties off-topic questions (docs/search-eval/, 2026-10-25)
MIN_SCORE = 0.01
# an unaccented question compared with unaccented text: right chunks 0.3-0.96, off-topic ones up to ~0.03 (eval)
MIN_SCORE_UNACCENTED = 0.1
RRF_K = 60
# a search is cached under the chunks' revision, so an ingest makes it stale at once; the TTL only bounds Redis
SEARCH_CACHE_TTL_SECONDS = 24 * 3600
# and under this module's code: a change to the ranking (thresholds, weights, rerank) ranks every question again
_RANKING_VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
WEIGHT_VECTOR = 0.6
WEIGHT_FTS = 0.4


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class TermExtractor(Protocol):
    async def terms(self, query: str) -> list[str]: ...


class Graph(Protocol):
    async def neighborhoods(
        self, terms: list[str], limit: int = ..., as_of: datetime | None = ...
    ) -> list[GraphFact]: ...


class Reranker(Protocol):
    async def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


class SearchCache(Protocol):  # the Redis client
    async def get(self, key: str) -> bytes | str | None: ...

    async def set(self, key: str, value: str, ex: int | None = None) -> object: ...


class SearchResult(BaseModel):
    text: str
    score: float
    source: Literal["vector", "graph", "fts"]
    spec_ids: list[str]
    headings: list[str] = []
    revision: str | None = None  # the spec revision a vector result's chunk was first written in (PoC-A)
    project_id: str | None = None
    reranked: bool = True  # False: the re-ranker was down and the order is the fused one, off-topic hits not dropped


# what search tools put first when the re-ranker was down, so the agent weighs the hits accordingly
UNRANKED_WARNING = (
    "⚠️ Reranker không phản hồi: các kết quả dưới đây chưa được xếp hạng lại, thứ tự kém tin cậy hơn và câu hỏi "
    "lạc đề vẫn có thể ra kết quả. Đối chiếu kỹ trước khi kết luận."
)


@dataclass(frozen=True)
class _Candidate:
    rerank_text: str  # what the cross-encoder reads: a chunk with its headings, or a graph fact
    result: SearchResult


def _fuse_rrf(
    semantic: list[_Candidate],
    fts: list[_Candidate],
    k: int = RRF_K,
    w_vec: float = WEIGHT_VECTOR,
    w_fts: float = WEIGHT_FTS,
) -> list[_Candidate]:
    """Combine dense (vector) and sparse (fts) chunk candidates via Reciprocal Rank Fusion."""
    if not fts:
        return semantic
    if not semantic:
        return fts

    candidates_by_text: dict[str, _Candidate] = {}
    rrf_scores: dict[str, float] = {}

    for rank, c in enumerate(semantic):
        candidates_by_text[c.rerank_text] = c
        rrf_scores[c.rerank_text] = rrf_scores.get(c.rerank_text, 0.0) + (w_vec / (k + rank + 1))

    for rank, c in enumerate(fts):
        if c.rerank_text not in candidates_by_text:
            candidates_by_text[c.rerank_text] = c
        rrf_scores[c.rerank_text] = rrf_scores.get(c.rerank_text, 0.0) + (w_fts / (k + rank + 1))

    sorted_texts = sorted(rrf_scores.keys(), key=lambda t: rrf_scores[t], reverse=True)
    return [candidates_by_text[t] for t in sorted_texts]


class HybridRetriever:
    def __init__(
        self,
        *,
        embedder: Embedder,
        vectors: VectorStore,
        term_extractor: TermExtractor,
        graph: Graph,
        reranker: Reranker,
        graph_search: bool = True,
        cache: SearchCache | None = None,
    ) -> None:
        self._embedder = embedder
        self._vectors = vectors
        self._term_extractor = term_extractor
        self._graph = graph
        self._reranker = reranker
        self._graph_search = graph_search
        self._cache = cache

    @property
    def embedder(self) -> Embedder:
        """The embedder of the search, reused to embed an approved proposal (api/proposals.py)."""
        return self._embedder

    @property
    def vectors(self) -> VectorStore:
        """The vector store used for embeddings and similarity search."""
        return self._vectors

    async def search(
        self, query: str, as_of: datetime | None = None, project_id: str | None = None, *, cached: bool = True
    ) -> list[SearchResult]:
        """`cached=False` ranks again whatever is cached (scripts/eval_search.py measures the ranking itself)."""
        started = time.perf_counter()
        key = await self._cache_key(query, as_of, project_id) if cached else None
        if key and (cached := await self._cached(key)) is not None:
            return cached
        (semantic, semantic_ms), (fts, fts_ms), (relational, relational_ms) = await asyncio.gather(
            _timed(self._semantic(query, as_of, project_id)),
            _timed(self._fts(query, as_of, project_id)),
            _timed(self._relational(query, as_of)),
        )
        chunk_candidates = _fuse_rrf(semantic, fts)
        candidates = list({c.rerank_text: c for c in [*chunk_candidates, *relational]}.values())
        try:
            scores, rerank_ms = await _timed(self._rerank(query, [c.rerank_text for c in candidates]))
        except DependencyUnavailableError as error:
            # no re-ranker (down, too slow on a CPU, not deployed): the search still answers, unranked (issue 4.3)
            log.warning(
                "[HybridRetriever] reranker unavailable (%s): vector/hybrid hits by score, then graph facts",
                error,
            )
            return [c.result.model_copy(update={"reranked": False}) for c in candidates][:TOP_K]
        # the sides overlap: total is about max(semantic, fts, relational) + rerank, not their sum
        log.info(
            "[HybridRetriever] semantic %d ms, fts %d ms, relational %d ms, rerank %d ms (%d candidates), total %d ms",
            semantic_ms,
            fts_ms,
            relational_ms,
            rerank_ms,
            len(candidates),
            (time.perf_counter() - started) * 1000,
        )
        ranked = sorted(
            (c.result.model_copy(update={"score": s}) for c, s in zip(candidates, scores, strict=True)),
            key=lambda r: r.score,
            reverse=True,
        )
        results = [r for r in ranked if r.score >= MIN_SCORE][:TOP_K]
        if key:
            await self._store(key, results)
        return results

    async def _cache_key(self, query: str, as_of: datetime | None, project_id: str | None) -> str | None:
        """None when the search is not cached: no Redis, a search in the past, or no chunk revision to key it on."""
        revision = getattr(self._vectors, "revision", None)
        if self._cache is None or as_of is not None or revision is None or self._graph_search:
            return None  # graph facts change with the graph ingestion, which the chunk revision does not follow
        try:
            chunks = await revision()
        except DependencyUnavailableError:
            return None
        words = " ".join(query.lower().split())
        digest = hashlib.sha256(f"{(project_id or '').lower()}\n{words}".encode()).hexdigest()
        return f"kb:search:{_RANKING_VERSION}:{chunks}:{digest}"

    async def _cached(self, key: str) -> list[SearchResult] | None:
        try:
            raw = await self._cache.get(key)
        except Exception as exc:  # Redis down: search as if nothing was cached
            log.warning("[HybridRetriever] search cache unavailable: %s", type(exc).__name__)
            return None
        if raw is None:
            return None
        try:
            return [SearchResult.model_validate(r) for r in json.loads(raw)]
        except ValueError:  # not JSON, or written by a SearchResult of other fields: rank again
            return None

    async def _store(self, key: str, results: list[SearchResult]) -> None:
        payload = json.dumps([r.model_dump() for r in results], ensure_ascii=False)
        try:
            await self._cache.set(key, payload, ex=SEARCH_CACHE_TTL_SECONDS)
        except Exception as exc:
            log.warning("[HybridRetriever] search cache unavailable: %s", type(exc).__name__)

    async def _rerank(self, query: str, texts: list[str]) -> list[float]:
        """Cross-encoder scores; a question typed without diacritics is also compared with unaccented text.

        bge-reranker scores "nghi phep nam" ~0.02 against "Nghỉ phép năm" but ~0.96 against "Nghi phep nam". An ASCII
        question may as well be English ("Dynamic Island notch" ~0.04 as written), so the unaccented score replaces
        the written one only when it is strong (eval, 2026-10-25).
        """
        scores = await self._reranker.score(query, texts)
        if query != _unaccent(query):
            return scores
        # a text without diacritics would only be scored again as it is
        plain = {i: p for i, t in enumerate(texts) if (p := _unaccent(t)) != t}
        if not plain:
            return scores
        plain_scores = dict(zip(plain, await self._reranker.score(query, list(plain.values())), strict=True))
        return [
            max(s, p if (p := plain_scores.get(i, 0.0)) >= MIN_SCORE_UNACCENTED else 0.0) for i, s in enumerate(scores)
        ]

    async def _semantic(self, query: str, as_of: datetime | None, project_id: str | None = None) -> list[_Candidate]:
        [vector] = await self._embedder.embed([query])
        try:
            if project_id:
                hits = await self._vectors.search(vector, SEMANTIC_LIMIT, as_of, project_id=project_id)
            else:
                hits = await self._vectors.search(vector, SEMANTIC_LIMIT, as_of)
        except TypeError:
            hits = await self._vectors.search(vector, SEMANTIC_LIMIT, as_of)
        return [
            _Candidate(
                rerank_text="\n".join([*h.headings, h.content]),
                result=SearchResult(
                    text=h.content,
                    score=h.score,
                    source="vector",
                    spec_ids=[h.spec_id],
                    headings=h.headings,
                    revision=h.revision,
                    project_id=getattr(h, "project_id", "Personal-KB"),
                ),
            )
            for h in hits
        ]

    async def _fts(self, query: str, as_of: datetime | None, project_id: str | None = None) -> list[_Candidate]:
        if not hasattr(self._vectors, "search_fts"):
            return []
        try:
            if project_id:
                hits = await self._vectors.search_fts(query, SEMANTIC_LIMIT, as_of, project_id=project_id)
            else:
                hits = await self._vectors.search_fts(query, SEMANTIC_LIMIT, as_of)
        except Exception as exc:
            log.warning("[HybridRetriever] fts search failed: %s", exc)
            return []
        return [
            _Candidate(
                rerank_text="\n".join([*h.headings, h.content]),
                result=SearchResult(
                    text=h.content,
                    score=h.score,
                    source="fts",
                    spec_ids=[h.spec_id],
                    headings=h.headings,
                    revision=h.revision,
                    project_id=getattr(h, "project_id", "Personal-KB"),
                ),
            )
            for h in hits
        ]

    async def _relational(self, query: str, as_of: datetime | None) -> list[_Candidate]:
        if not self._graph_search:  # no graph ingested: naming the terms costs an LLM call and finds nothing
            return []
        # the graph only adds facts to the vector results: when it or the model naming its terms is down, the search
        # still answers from the vector side
        try:
            terms = await self._term_extractor.terms(query)
            facts = await self._graph.neighborhoods(terms, limit=GRAPH_LIMIT, as_of=as_of) if terms else []
        except (DependencyUnavailableError, openai.OpenAIError) as exc:
            log.warning("[HybridRetriever] graph side unavailable, vector results only: %s", type(exc).__name__)
            return []
        return [
            _Candidate(
                rerank_text=f.text,
                result=SearchResult(text=f.text, score=0.0, source="graph", spec_ids=f.spec_ids),
            )
            for f in facts
        ]


def _unaccent(text: str) -> str:
    """Vietnamese without diacritics, as people type when they skip them: "Nghỉ phép năm" -> "Nghi phep nam"."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


T = TypeVar("T")


async def _timed(work: Awaitable[T]) -> tuple[T, float]:
    started = time.perf_counter()
    result = await work
    return result, (time.perf_counter() - started) * 1000
