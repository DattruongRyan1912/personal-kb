from httpx import ASGITransport, AsyncClient

from scripts.local_reranker import create_app


def fake_scorer(pairs):
    """Scores a pair by how often the query's first word appears in the text."""
    return [text.count(query.split()[0]) / 10 for query, text in pairs]


async def rerank(body):
    async with AsyncClient(transport=ASGITransport(app=create_app(fake_scorer)), base_url="http://test") as client:
        return await client.post("/rerank", json=body)


async def test_rerank_answers_like_tei_best_first_with_input_indexes():
    response = await rerank({"query": "email table", "texts": ["users", "email email", "email"], "truncate": True})

    assert response.status_code == 200
    assert response.json() == [{"index": 1, "score": 0.2}, {"index": 2, "score": 0.1}, {"index": 0, "score": 0.0}]


async def test_no_texts_gives_no_scores():
    assert (await rerank({"query": "q", "texts": []})).json() == []


def test_it_listens_on_localhost_only_by_default():
    from scripts.local_reranker import parse_args

    assert parse_args([]).host == "127.0.0.1"
    assert parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"


def test_the_token_budget_per_pair_is_a_flag():
    from scripts.local_reranker import parse_args

    assert parse_args([]).max_length == 512
    assert parse_args(["--max-length", "256"]).max_length == 256


async def test_concurrent_requests_are_scored_one_at_a_time():
    # the model on the Mac GPU is not thread-safe: two searches at once crashed one with a 500 (2026-10-25)
    import asyncio
    import threading
    import time

    active, overlaps, lock = [0], [], threading.Lock()

    def slow_scorer(pairs):
        with lock:
            active[0] += 1
            overlaps.append(active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return [0.5 for _ in pairs]

    async with AsyncClient(transport=ASGITransport(app=create_app(slow_scorer)), base_url="http://test") as client:
        responses = await asyncio.gather(
            *(client.post("/rerank", json={"query": "q", "texts": ["a", "b"]}) for _ in range(4))
        )

    assert [r.status_code for r in responses] == [200] * 4
    assert max(overlaps) == 1
