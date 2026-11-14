from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from personal_kb.api.worklog import get_worklog_projects, get_worklog_store
from personal_kb.main import create_app
from personal_kb.services.worklog import NewWorklogEntry, WorklogEntry
from personal_kb.tools.base import ToolContext
from tests.conftest import make_settings


class FakeStore:
    def __init__(self):
        self.rows: list[WorklogEntry] = []

    async def add(self, entry: NewWorklogEntry) -> WorklogEntry:
        row = WorklogEntry(**vars(entry), id=len(self.rows) + 1, created_at=datetime(2026, 10, 24, tzinfo=UTC))
        self.rows.append(row)
        return row

    async def recent(self, project: str, *, limit: int = 10, kind: str = ""):
        rows = [r for r in self.rows if r.project == project and (not kind or r.kind == kind)]
        return list(reversed(rows))[:limit]


@pytest.fixture
def app():
    app = create_app(make_settings(supabase_url="http://localhost:54321", dev_login=True))
    store = FakeStore()
    app.dependency_overrides[get_worklog_store] = lambda: store
    app.dependency_overrides[get_worklog_projects] = lambda: frozenset({"personal-kb"})
    return app


def client_for(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


BODY = {"project": "personal-kb", "kind": "progress", "summary": "xong task 4", "agent": "claude"}


async def test_post_then_get_round_trip(app):
    async with client_for(app) as c:
        resp = await c.post("/api/v1/agent/worklog", json=BODY)
        assert resp.status_code == 201
        created = resp.json()
        assert set(created) == {
            "id",
            "project",
            "kind",
            "summary",
            "next_steps",
            "agent",
            "session_id",
            "branch",
            "created_at",
        }
        assert created["created_at"].startswith("2026-10-24T00:00:00")
        got = await c.get("/api/v1/agent/worklog", params={"project": "personal-kb"})
        assert got.status_code == 200
        assert got.json() == [created]
        none = await c.get("/api/v1/agent/worklog", params={"project": "personal-kb", "kind": "gotcha"})
        assert none.json() == []


async def test_post_unknown_kind_is_422(app):
    async with client_for(app) as c:
        resp = await c.post("/api/v1/agent/worklog", json={**BODY, "kind": "nope"})
        assert resp.status_code == 422
        assert "kind phải là một trong" in resp.json()["detail"]


async def test_post_unknown_project_and_non_string_are_422(app):
    async with client_for(app) as c:
        assert (await c.post("/api/v1/agent/worklog", json={**BODY, "project": "x"})).status_code == 422
        assert (await c.post("/api/v1/agent/worklog", json={**BODY, "summary": 5})).status_code == 422


async def test_get_validation(app):
    async with client_for(app) as c:
        assert (await c.get("/api/v1/agent/worklog", params={"project": "personal-kb", "limit": 51})).status_code == 422
        assert (await c.get("/api/v1/agent/worklog", params={"project": "x"})).status_code == 422
        resp = await c.get("/api/v1/agent/worklog", params={"project": "personal-kb", "kind": "nope"})
        assert resp.status_code == 422


async def test_get_limit_over_50_is_422(app):
    async with client_for(app) as c:
        resp = await c.get("/api/v1/agent/worklog", params={"project": "personal-kb", "limit": 51})
        assert resp.status_code == 422


async def test_no_store_is_503():
    app = create_app(make_settings(supabase_url="http://localhost:54321", dev_login=True))
    app.state.tool_context = ToolContext(retriever=None, documents=None)
    async with client_for(app) as c:
        resp = await c.get("/api/v1/agent/worklog", params={"project": "personal-kb"})
        assert resp.status_code == 503
