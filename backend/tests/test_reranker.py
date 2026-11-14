import json

import httpx
import pytest

from personal_kb.core.exceptions import DependencyUnavailableError
from personal_kb.services.reranker import TeiReranker


def reranker(handler) -> TeiReranker:
    return TeiReranker(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://reranker"))


async def test_scores_come_back_in_the_order_of_the_texts():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        # TEI answers sorted by score, best first
        return httpx.Response(
            200, json=[{"index": 2, "score": 0.9}, {"index": 0, "score": 0.4}, {"index": 1, "score": 0.1}]
        )

    scores = await reranker(handler).score("which table?", ["a", "b", "c"])

    assert scores == [0.4, 0.1, 0.9]
    assert seen["path"] == "/rerank"
    assert seen["body"] == {"query": "which table?", "texts": ["a", "b", "c"], "raw_scores": False, "truncate": True}


async def test_no_texts_means_no_request():
    def handler(request):
        raise AssertionError("no request expected")

    assert await reranker(handler).score("q", []) == []


async def test_an_unreachable_reranker_is_reported_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(DependencyUnavailableError) as excinfo:
        await reranker(handler).score("q", ["a"])
    assert excinfo.value.dependency == "reranker"


async def test_a_reranker_error_response_is_reported_as_unavailable():
    with pytest.raises(DependencyUnavailableError):
        await reranker(lambda request: httpx.Response(503, text="model loading")).score("q", ["a"])
