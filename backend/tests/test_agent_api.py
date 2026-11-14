import pytest
from httpx import ASGITransport, AsyncClient

from personal_kb.api.agent import get_agent, get_documents, get_retriever
from personal_kb.main import create_app
from personal_kb.services.memory_ports import SpecDocument
from personal_kb.services.retrieval import SearchResult
from tests.conftest import make_settings


class DummyRetriever:
    async def search(self, query: str):
        return [
            SearchResult(
                text="Chính sách bảo hiểm y tế doanh nghiệp chi trả 100%.",
                score=0.92,
                source="vector",
                spec_ids=["HR-M02"],
                headings=["Phúc lợi", "Bảo hiểm"],
            )
        ]


class DummyDocuments:
    def __init__(self):
        self._docs = {
            "HR-M02": SpecDocument(
                spec_id="HR-M02",
                title="Hồ sơ nhân sự và Hợp đồng",
                content=(
                    "---\nid: HR-M02\ntitle: Hồ sơ nhân sự và Hợp đồng\nowner: Ryan Truong\nstatus: active\n---\n"
                    "# 1. Hồ sơ nhân sự"
                ),
            )
        }

    async def get(self, spec_id: str):
        return self._docs.get(spec_id)

    async def all(self):
        return list(self._docs.values())


class DummyAgent:
    async def ask(self, user_id: str, session_id: str, query: str, ctx=None):
        from langchain_core.messages import AIMessage

        return AIMessage("Theo tài liệu [Hồ sơ nhân sự](HR-M02), bảo hiểm được chi trả 100%.")


@pytest.fixture
def test_app():
    settings = make_settings(supabase_url="http://localhost:54321", dev_login=True)
    app = create_app(settings)
    app.dependency_overrides[get_retriever] = lambda: DummyRetriever()
    app.dependency_overrides[get_documents] = lambda: DummyDocuments()
    app.dependency_overrides[get_agent] = lambda: DummyAgent()
    return app


async def test_agent_tools_search(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/agent/tools/search", json={"query": "bảo hiểm", "limit": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "bảo hiểm"
        assert data["total"] == 1
        assert data["results"][0]["spec_ids"] == ["HR-M02"]
        assert "0.92" in str(data["results"][0]["score"])


async def test_agent_tools_specs_catalog(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/agent/tools/specs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["specs"][0]["spec_id"] == "HR-M02"
        assert data["specs"][0]["owner"] == "Ryan Truong"


async def test_agent_tools_get_spec_detail(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/agent/tools/specs/HR-M02")
        assert resp.status_code == 200
        data = resp.json()
        assert data["spec_id"] == "HR-M02"
        assert "# 1. Hồ sơ nhân sự" in data["content"]


async def test_agent_tools_get_spec_not_found(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/agent/tools/specs/HR-UNKNOWN")
        assert resp.status_code == 404
        assert resp.json()["error"] == "SPEC_NOT_FOUND"


async def test_agent_query_m2m(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/agent/query", json={"query": "Chính sách bảo hiểm thế nào?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "HR-M02" in data["answer"]
        assert data["sources"] == ["HR-M02"]


async def test_agent_auth_with_agent_key():
    settings = make_settings(agent_api_key="sk-agent-secret-key-123", dev_login=False)
    app = create_app(settings)
    app.dependency_overrides[get_documents] = lambda: DummyDocuments()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Without key -> 401
        res_unauth = await client.get("/api/v1/agent/tools/specs")
        assert res_unauth.status_code == 401

        # With valid X-Agent-Key -> 200
        res_auth = await client.get("/api/v1/agent/tools/specs", headers={"X-Agent-Key": "sk-agent-secret-key-123"})
        assert res_auth.status_code == 200
        assert res_auth.json()["total"] == 1
