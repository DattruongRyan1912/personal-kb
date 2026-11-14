import asyncio
import logging
from datetime import UTC, datetime

import httpx
import openai
import pytest

from personal_kb.core.exceptions import DependencyUnavailableError
from personal_kb.services.graph_text import GraphFact
from personal_kb.services.memory_ports import ChunkHit
from personal_kb.services.retrieval import HybridRetriever


class FakeEmbedder:
    def __init__(self, before=None):
        self.before = before  # awaited before answering, to test concurrency

    async def embed(self, texts):
        if self.before:
            await self.before()
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class FakeTerms:
    def __init__(self, terms, on_call=None):
        self._terms, self.on_call = terms, on_call

    async def terms(self, query):
        if self.on_call:
            self.on_call()
        return self._terms


class FakeGraph:
    def __init__(self, facts):
        self.facts, self.calls, self.as_ofs = facts, [], []

    async def neighborhoods(self, terms, limit=10, as_of=None):
        self.calls.append(terms)
        self.as_ofs.append(as_of)
        return self.facts


class FailingTerms:
    async def terms(self, query):
        raise openai.APIConnectionError(request=httpx.Request("POST", "http://llm/v1/chat/completions"))


class FailingGraph:
    async def neighborhoods(self, terms, limit=10, as_of=None):
        raise DependencyUnavailableError("neo4j", "connection refused")


class FakeReranker:
    """Scores texts by the first matching keyword in `by_keyword`; 0.5 otherwise. Records what it was asked."""

    def __init__(self, by_keyword=None):
        self.by_keyword, self.texts, self.calls = by_keyword or {}, [], []

    async def score(self, query, texts):
        self.texts = list(texts)
        self.calls.append(list(texts))
        return [next((s for k, s in self.by_keyword.items() if k in t), 0.5) for t in texts]


class FakeVectorStore:
    """Returns its hits best first, at most `limit`; records every search."""

    def __init__(self):
        self.hits: list[ChunkHit] = []
        self.limits, self.as_ofs = [], []

    async def search(self, vector, limit, as_of=None, project_id=None):
        self.limits.append(limit)
        self.as_ofs.append(as_of)
        return self.hits[:limit]


@pytest.fixture
def vectors():
    return FakeVectorStore()


def add_chunks(vectors, *contents, spec_id="SPC-1", revision=None):
    start = len(vectors.hits)
    vectors.hits += [
        ChunkHit(
            spec_id=spec_id,
            chunk_key=f"k{start + i}-0",
            valid_from=datetime(2026, 10, 1, tzinfo=UTC),
            headings=["# 1. Overview"],
            content=c,
            revision=revision,
            score=1.0 - 0.01 * (start + i),
        )
        for i, c in enumerate(contents)
    ]


def retriever(vectors, *, terms=(), facts=(), reranker=None, embedder=None, term_extractor=None, graph=None):
    return HybridRetriever(
        embedder=embedder or FakeEmbedder(),
        vectors=vectors,
        term_extractor=term_extractor or FakeTerms(list(terms)),
        graph=graph or FakeGraph(list(facts)),
        reranker=reranker or FakeReranker(),
    )


async def test_vector_and_graph_results_are_reranked_together(vectors):
    add_chunks(vectors, "chunk about login", "chunk about checkout")
    fact = GraphFact(
        node_id="api:post_email",
        text="API_Endpoint post_email\n- MODIFIES -> Database_Table outbox",
        spec_ids=["SPC-3"],
    )
    reranker = FakeReranker({"post_email": 0.95, "login": 0.6, "checkout": 0.4})

    results = await retriever(vectors, terms=["email"], facts=[fact], reranker=reranker).search("which table?")

    assert [(r.source, r.score) for r in results] == [("graph", 0.95), ("vector", 0.6), ("vector", 0.4)]
    assert results[0].spec_ids == ["SPC-3"] and results[0].text == fact.text
    assert results[1].spec_ids == ["SPC-1"] and results[1].headings == ["# 1. Overview"]
    assert results[1].text == "chunk about login"


async def test_results_below_the_threshold_are_dropped_and_at_most_five_are_kept(vectors):
    add_chunks(vectors, *(f"chunk {i}" for i in range(8)), "weak chunk")
    reranker = FakeReranker({"weak": 0.009})

    results = await retriever(vectors, reranker=reranker).search("q")

    assert len(results) == 5
    assert all(r.score >= 0.01 for r in results)


async def test_a_low_but_relevant_rerank_score_is_kept(vectors):
    # bge-reranker gives short or unaccented questions ~0.02 on their right chunk, ~0.001 off topic (eval 2026-10-25)
    add_chunks(vectors, "chunk about notch", "chunk about bitcoin")
    reranker = FakeReranker({"notch": 0.03, "bitcoin": 0.001})

    results = await retriever(vectors, reranker=reranker).search("Dynamic Island notch")

    assert [r.text for r in results] == ["chunk about notch"]


async def test_the_reranker_sees_headings_with_chunks_and_each_text_once(vectors):
    add_chunks(vectors, "same text")
    duplicate = GraphFact(node_id="x:y", text="# 1. Overview\nsame text", spec_ids=["SPC-9"])
    reranker = FakeReranker()

    await retriever(vectors, terms=["t"], facts=[duplicate, duplicate], reranker=reranker).search("q")

    assert reranker.texts == ["# 1. Overview\nsame text"]


async def test_the_semantic_side_asks_the_vector_store_for_at_most_15_chunks(vectors):
    add_chunks(vectors, *(f"chunk {i}" for i in range(20)))
    reranker = FakeReranker()

    await retriever(vectors, reranker=reranker).search("q")

    assert len(reranker.texts) == 15
    assert vectors.limits == [15]


async def test_without_terms_the_graph_is_not_queried(vectors):
    add_chunks(vectors, "a chunk")
    r = retriever(vectors, terms=[])

    await r.search("q")

    assert r._graph.calls == []


async def test_the_semantic_and_relational_sides_run_concurrently(vectors):
    add_chunks(vectors, "a chunk")
    terms_started = asyncio.Event()
    # the embedder only answers once the term extraction has started: a sequential search would wait forever
    r = retriever(
        vectors,
        embedder=FakeEmbedder(before=terms_started.wait),
        term_extractor=FakeTerms(["t"], on_call=terms_started.set),
    )

    results = await asyncio.wait_for(r.search("q"), timeout=2)

    assert results


async def test_each_search_logs_the_time_of_every_stage(vectors, caplog):
    import logging

    caplog.set_level(logging.INFO)
    add_chunks(vectors, "a chunk")

    await retriever(vectors, terms=["t"]).search("q")

    line = next(r.getMessage() for r in caplog.records if "[HybridRetriever]" in r.getMessage())
    for stage in ("semantic", "fts", "relational", "rerank", "total"):
        assert f"{stage} " in line and " ms" in line


@pytest.mark.parametrize(
    "side",
    [{"term_extractor": FailingTerms()}, {"terms": ["users"], "graph": FailingGraph()}],
    ids=["term extraction fails", "graph unavailable"],
)
async def test_a_failing_graph_side_leaves_the_vector_results(vectors, caplog, side):
    add_chunks(vectors, "Bảng users lưu tài khoản")
    with caplog.at_level(logging.WARNING, logger="personal_kb.services.retrieval"):
        results = await retriever(vectors, **side).search("bảng users")
    assert [r.source for r in results] == ["vector"]
    assert "graph side unavailable" in caplog.text


class DownReranker:
    async def score(self, query, texts):
        from personal_kb.core.exceptions import DependencyUnavailableError

        raise DependencyUnavailableError("reranker", "connection refused")


async def test_without_a_reranker_the_search_keeps_the_vector_then_graph_order(vectors, caplog):
    add_chunks(vectors, *(f"chunk {i}" for i in range(7)))
    fact = GraphFact(node_id="api:x", text="API x\n- MODIFIES -> Database_Table y", spec_ids=["SPC-3"])

    results = await retriever(vectors, terms=["x"], facts=[fact], reranker=DownReranker()).search("q")

    assert [r.source for r in results] == ["vector"] * 5  # the best 5 by vector score, graph facts after them
    assert [r.text for r in results] == [f"chunk {i}" for i in range(5)]
    assert "reranker unavailable" in caplog.text


async def test_without_a_reranker_graph_facts_fill_the_results_after_the_vector_hits(vectors):
    add_chunks(vectors, "only chunk")
    fact = GraphFact(node_id="api:x", text="API x", spec_ids=["SPC-3"])

    results = await retriever(vectors, terms=["x"], facts=[fact], reranker=DownReranker()).search("q")

    assert [(r.source, r.text) for r in results] == [("vector", "only chunk"), ("graph", "API x")]


async def test_the_time_asked_about_reaches_the_graph_too(vectors):
    graph = FakeGraph([])
    at = datetime(2026, 10, 1, tzinfo=UTC)

    await retriever(vectors, terms=["payments"], graph=graph).search("q", as_of=at)
    await retriever(vectors, terms=["payments"], graph=graph).search("q")

    assert graph.as_ofs == [at, None]


async def test_the_time_asked_about_reaches_the_vector_store_and_revisions_reach_the_results(vectors):
    add_chunks(vectors, "bảng payment_transactions", revision="2")
    at = datetime(2026, 10, 2, tzinfo=UTC)

    results = await retriever(vectors).search("bảng nào?", as_of=at)

    assert vectors.as_ofs == [at]
    assert [(r.text, r.revision, r.spec_ids) for r in results] == [("bảng payment_transactions", "2", ["SPC-1"])]


class FakeHybridVectorStore(FakeVectorStore):
    """Vector store that also supports FTS keyword search."""

    def __init__(self):
        super().__init__()
        self.fts_hits: list[ChunkHit] = []
        self.fts_queries: list[str] = []

    async def search_fts(self, query, limit, as_of=None, project_id=None):
        self.fts_queries.append(query)
        return self.fts_hits[:limit]


async def test_rrf_promotes_chunks_found_in_both_vector_and_fts():
    vectors = FakeHybridVectorStore()
    vectors.hits = [
        ChunkHit(
            spec_id="SPC-1",
            chunk_key="k1",
            valid_from=datetime(2026, 10, 1, tzinfo=UTC),
            headings=["# Vector Doc 1"],
            content="vector only chunk",
            revision="1",
            score=0.9,
        ),
        ChunkHit(
            spec_id="SPC-1",
            chunk_key="k2",
            valid_from=datetime(2026, 10, 1, tzinfo=UTC),
            headings=["# Common Doc"],
            content="both vector and fts chunk",
            revision="1",
            score=0.8,
        ),
    ]
    vectors.fts_hits = [
        ChunkHit(
            spec_id="SPC-1",
            chunk_key="k2",
            valid_from=datetime(2026, 10, 1, tzinfo=UTC),
            headings=["# Common Doc"],
            content="both vector and fts chunk",
            revision="1",
            score=0.95,
        ),
        ChunkHit(
            spec_id="SPC-2",
            chunk_key="k3",
            valid_from=datetime(2026, 10, 1, tzinfo=UTC),
            headings=["# FTS Doc"],
            content="fts only keyword match chunk",
            revision="1",
            score=0.7,
        ),
    ]
    # Without reranker: RRF fusion should rank the overlapping chunk top
    results = await retriever(vectors, reranker=DownReranker()).search("keyword")
    assert len(results) >= 2
    assert results[0].text == "both vector and fts chunk"
    assert "reranker unavailable" in "" or any(r.text == "fts only keyword match chunk" for r in results)


async def test_fts_only_chunks_are_included_and_not_dropped():
    vectors = FakeHybridVectorStore()
    vectors.hits = []
    vectors.fts_hits = [
        ChunkHit(
            spec_id="SPC-FTS",
            chunk_key="k_fts",
            valid_from=datetime(2026, 10, 1, tzinfo=UTC),
            headings=["# Exact Code"],
            content="DEF-404: exact error token",
            revision="1",
            score=0.99,
        )
    ]
    reranker = FakeReranker({"DEF-404": 0.92})
    results = await retriever(vectors, reranker=reranker).search("DEF-404")
    assert len(results) == 1
    assert results[0].text == "DEF-404: exact error token"
    assert results[0].source == "fts"
    assert results[0].score == 0.92


async def test_with_graph_search_off_the_question_is_never_sent_to_the_term_model(vectors):
    # no graph was ingested for this knowledge base: each search paid an LLM call and ~1 s for no fact (2026-10-25)
    add_chunks(vectors, "chunk about login")
    calls = []
    terms = FakeTerms(["login"], on_call=lambda: calls.append("called"))
    searcher = HybridRetriever(
        embedder=FakeEmbedder(),
        vectors=vectors,
        term_extractor=terms,
        graph=FakeGraph([]),
        reranker=FakeReranker(),
        graph_search=False,
    )

    results = await searcher.search("login?")

    assert calls == []
    assert [r.text for r in results] == ["chunk about login"]


async def test_an_unaccented_question_is_also_compared_with_unaccented_text(vectors):
    # bge-reranker scores "nghi phep nam" ~0.02 against "Nghỉ phép năm" but ~0.96 against "Nghi phep nam" (2026-10-25)
    add_chunks(vectors, "Nghỉ phép năm được 12 ngày")
    reranker = FakeReranker({"Nghi phep": 0.96})

    results = await retriever(vectors, reranker=reranker).search("nghi phep nam")

    assert [(r.text, r.score) for r in results] == [("Nghỉ phép năm được 12 ngày", 0.96)]


async def test_an_accented_question_is_compared_with_the_text_as_written_only(vectors):
    add_chunks(vectors, "Nghỉ phép năm được 12 ngày")
    reranker = FakeReranker()

    await retriever(vectors, reranker=reranker).search("nghỉ phép năm")

    assert reranker.calls == [["# 1. Overview\nNghỉ phép năm được 12 ngày"]]


async def test_a_weak_unaccented_match_does_not_keep_an_off_topic_chunk(vectors):
    # unaccented on both sides an off-topic question still scores ~0.03 ("cong thuc nau pho"), while an English
    # keyword question can score only ~0.013 on its right chunk as written: the unaccented score counts from 0.1
    add_chunks(vectors, "Bảng lương tháng")
    reranker = FakeReranker({"Bang luong": 0.05, "Bảng lương": 0.0})

    assert await retriever(vectors, reranker=reranker).search("cong thuc nau pho") == []


async def test_results_say_whether_they_were_reranked(vectors):
    # with the re-ranker down an agent got results in fused order with nothing telling it so (2026-10-25)
    add_chunks(vectors, "only chunk")

    ranked = await retriever(vectors, reranker=FakeReranker()).search("q")
    unranked = await retriever(vectors, reranker=DownReranker()).search("q")

    assert [r.reranked for r in ranked] == [True]
    assert [r.reranked for r in unranked] == [False]


async def test_an_unaccented_question_rescores_only_the_texts_that_have_diacritics(vectors):
    # unaccented, a text without diacritics is the same pair again: one more cross-encoder pass for nothing
    add_chunks(vectors, "Nghỉ phép năm được 12 ngày", "Release build with ditto")
    reranker = FakeReranker()

    await retriever(vectors, reranker=reranker).search("nghi phep nam")

    assert reranker.calls[1:] == [["# 1. Overview\nNghi phep nam duoc 12 ngay"]]


class FakeRedis:
    def __init__(self, fail=False):
        self.data, self.fail = {}, fail

    async def get(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.data[key] = value


class RevisedVectorStore(FakeVectorStore):
    def __init__(self):
        super().__init__()
        self.rev = "1"

    async def revision(self):
        return self.rev


def cached_retriever(vectors, reranker, cache):
    return HybridRetriever(
        embedder=FakeEmbedder(),
        vectors=vectors,
        term_extractor=FakeTerms([]),
        graph=FakeGraph([]),
        reranker=reranker,
        graph_search=False,
        cache=cache,
    )


async def test_the_same_question_is_answered_from_the_cache_until_the_chunks_change():
    # every search took 4-7 s, almost all of it the re-ranker, even for the question asked a moment before (2026-10-29)
    vectors, reranker = RevisedVectorStore(), FakeReranker({"Release": 0.9})
    add_chunks(vectors, "Release build with ditto")
    search = cached_retriever(vectors, reranker, FakeRedis()).search

    first = await search("MyNotch  Release", project_id="MyNotch")
    again = await search("mynotch release", project_id="mynotch")
    assert again == first and len(reranker.calls) == 1

    vectors.rev = "2"  # an ingest wrote, closed or moved chunks
    await search("mynotch release", project_id="MyNotch")
    assert len(reranker.calls) == 2


async def test_searches_of_another_project_or_the_past_are_not_answered_from_the_cache():
    vectors, reranker = RevisedVectorStore(), FakeReranker()
    add_chunks(vectors, "Release build with ditto")
    search = cached_retriever(vectors, reranker, FakeRedis()).search

    await search("release", project_id="MyNotch")
    await search("release", project_id="CyberOS")
    await search("release", project_id="MyNotch", as_of=datetime(2026, 10, 2, tzinfo=UTC))
    await search("release", project_id="MyNotch", as_of=datetime(2026, 10, 2, tzinfo=UTC))

    assert len(reranker.calls) == 4


async def test_with_redis_down_the_search_still_answers(caplog):
    vectors, reranker = RevisedVectorStore(), FakeReranker({"Release": 0.9})
    add_chunks(vectors, "Release build with ditto")

    results = await cached_retriever(vectors, reranker, FakeRedis(fail=True)).search("release")

    assert [r.text for r in results] == ["Release build with ditto"]
    assert "search cache unavailable" in caplog.text


async def test_a_new_ranking_or_an_unreadable_entry_ranks_the_question_again(monkeypatch):
    from personal_kb.services import retrieval

    vectors, reranker, cache = RevisedVectorStore(), FakeReranker(), FakeRedis()
    add_chunks(vectors, "Release build with ditto")
    search = cached_retriever(vectors, reranker, cache).search
    await search("release")

    monkeypatch.setattr(retrieval, "_RANKING_VERSION", "other")  # retrieval.py changed: thresholds, weights, rerank
    await search("release")
    assert len(reranker.calls) == 2

    for key in cache.data:
        cache.data[key] = '[{"text": 1}]'
    assert [r.text for r in await search("release")] == ["Release build with ditto"]
    assert len(reranker.calls) == 3


async def test_the_eval_ranks_every_question_even_when_cached():
    vectors, reranker = RevisedVectorStore(), FakeReranker()
    add_chunks(vectors, "Release build with ditto")
    search = cached_retriever(vectors, reranker, FakeRedis()).search
    await search("release")

    await search("release", cached=False)

    assert len(reranker.calls) == 2
