from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from personal_kb.api.memory import get_retriever
from personal_kb.core.exceptions import DependencyUnavailableError
from personal_kb.main import create_app
from personal_kb.services.retrieval import SearchResult
from tests.conftest import auth_headers, make_settings


class FakeRetriever:
    def __init__(self, results=(), error=None):
        self.results, self.error, self.queries, self.as_ofs = list(results), error, [], []

    async def search(self, query, as_of=None):
        self.queries.append(query)
        self.as_ofs.append(as_of)
        if self.error:
            raise self.error
        return self.results


def app_with(retriever):
    app = create_app(make_settings())
    app.dependency_overrides[get_retriever] = lambda: retriever
    return app


async def post(app, body, headers=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/api/v1/memory/search", json=body, headers=auth_headers() if headers is None else headers
        )


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-jwt"}, auth_headers(exp=1), auth_headers(aud="anon")],
)
async def test_search_needs_a_valid_user_token(headers):
    retriever = FakeRetriever()

    response = await post(app_with(retriever), {"query": "q"}, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"] == "UNAUTHENTICATED"
    assert retriever.queries == []


@pytest.mark.parametrize("body", [{"query": ""}, {"query": "   "}, {}])
async def test_an_empty_query_is_rejected_with_422(body):
    retriever = FakeRetriever()

    response = await post(app_with(retriever), body)

    assert response.status_code == 422
    assert retriever.queries == []


async def test_search_returns_results_with_citation_metadata_and_timing():
    result = SearchResult(text="API_Endpoint post_email", score=0.91, source="graph", spec_ids=["SPC-3"])
    retriever = FakeRetriever(results=[result])

    response = await post(app_with(retriever), {"query": "  API gửi mail đăng ký ảnh hưởng bảng nào?  "})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "API gửi mail đăng ký ảnh hưởng bảng nào?"
    assert body["results"] == [
        {
            "text": "API_Endpoint post_email",
            "score": 0.91,
            "source": "graph",
            "spec_ids": ["SPC-3"],
            "headings": [],
            "revision": None,  # only a vector result names the spec revision it was read from (PoC-A)
            "project_id": None,
            "reranked": True,
        }
    ]
    assert isinstance(body["took_ms"], int)
    assert retriever.queries == ["API gửi mail đăng ký ảnh hưởng bảng nào?"]


async def test_an_unavailable_dependency_answers_503():
    response = await post(app_with(FakeRetriever(error=DependencyUnavailableError("reranker"))), {"query": "q"})

    assert response.status_code == 503
    assert response.json()["error"] == "RERANKER_UNAVAILABLE"


async def test_an_openai_failure_answers_503_without_echoing_the_upstream_message():
    import httpx2
    import openai

    request = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")
    error = openai.AuthenticationError(
        "Incorrect API key provided: sk-abc***xyz", response=httpx2.Response(401, request=request), body=None
    )

    response = await post(app_with(FakeRetriever(error=error)), {"query": "q"})

    assert response.status_code == 503
    assert response.json()["error"] == "OPENAI_UNAVAILABLE"
    assert "sk-" not in response.text


async def test_the_time_asked_about_reaches_the_retriever():
    retriever = FakeRetriever()

    response = await post(app_with(retriever), {"query": "q", "as_of": "2026-10-01T12:00:00+07:00"})

    assert response.status_code == 200
    assert retriever.as_ofs == [datetime(2026, 10, 1, 5, 0, tzinfo=UTC)]


async def test_a_time_without_a_timezone_is_refused():
    response = await post(app_with(FakeRetriever()), {"query": "q", "as_of": "2026-10-01T12:00:00"})

    assert response.status_code == 422


async def test_no_time_means_now():
    retriever = FakeRetriever()

    await post(app_with(retriever), {"query": "q"})

    assert retriever.as_ofs == [None]
