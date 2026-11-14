import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from personal_kb.api.chat import get_memory
from personal_kb.main import create_app
from personal_kb.services.session_memory import SessionMemoryManager, TranscriptEntry
from tests.conftest import auth_headers, make_settings

ME = "7b1e0000-0000-4000-8000-000000000001"  # the subject of auth_headers()


class NoSummaries:
    async def summarize(self, previous, messages):
        raise AssertionError("not expected")


@pytest.fixture
def memory():
    return SessionMemoryManager(fakeredis.FakeAsyncRedis(), summarizer=NoSummaries(), threshold_tokens=100_000)


@pytest.fixture
def app(memory):
    app = create_app(make_settings())
    app.dependency_overrides[get_memory] = lambda: memory
    return app


async def call(app, method, path, headers=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, headers=auth_headers() if headers is None else headers)


async def test_history_needs_a_signed_in_user(app):
    assert (await call(app, "GET", "/api/v1/chat/sessions/s1/messages", headers={})).status_code == 401


async def test_history_returns_the_users_messages_with_roles(app, memory):
    tool_call = AIMessage("", tool_calls=[{"id": "c1", "name": "search_sdd_knowledge", "args": {"query": "x"}}])
    await memory.add_messages(
        ME,
        "s1",
        [
            HumanMessage("Tìm luồng thanh toán"),
            tool_call,
            ToolMessage("SPC-2", tool_call_id="c1"),
            AIMessage("Xem [Thanh toán](SPC-2)"),
        ],
    )

    response = await call(app, "GET", "/api/v1/chat/sessions/s1/messages")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "s1"
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("user", "Tìm luồng thanh toán"),
        ("assistant", ""),
        ("tool", "SPC-2"),
        ("assistant", "Xem [Thanh toán](SPC-2)"),
    ]
    assert body["messages"][1]["tool_calls"][0]["name"] == "search_sdd_knowledge"
    assert body["messages"][2]["tool_call_id"] == "c1"


async def test_another_users_token_sees_nothing(app, memory):
    await memory.add_messages(ME, "s1", [HumanMessage("riêng tư")])

    response = await call(app, "GET", "/api/v1/chat/sessions/s1/messages", headers=auth_headers(sub="someone-else"))

    assert response.json()["messages"] == []


async def test_sessions_are_listed_with_titles_and_deleted(app, memory):
    await memory.add_messages(ME, "s1", [HumanMessage("a")])
    await memory.add_to_transcript(ME, "s1", [TranscriptEntry("user", "Luồng thanh toán?")])

    sessions = (await call(app, "GET", "/api/v1/chat/sessions")).json()["sessions"]
    assert [(s["session_id"], s["title"]) for s in sessions] == [("s1", "Luồng thanh toán?")]
    assert isinstance(sessions[0]["updated_at"], float)
    assert (await call(app, "DELETE", "/api/v1/chat/sessions/s1")).status_code == 204
    assert (await call(app, "GET", "/api/v1/chat/sessions")).json() == {"sessions": []}


async def test_the_transcript_is_what_the_chat_window_shows(app, memory):
    entries = [TranscriptEntry("user", "Tìm luồng thanh toán"), TranscriptEntry("assistant", "Đó là", stopped=True)]
    await memory.add_to_transcript(ME, "s1", entries)

    body = (await call(app, "GET", "/api/v1/chat/sessions/s1/transcript")).json()

    assert body == {
        "session_id": "s1",
        "messages": [
            {"role": "user", "content": "Tìm luồng thanh toán", "stopped": False},
            {"role": "assistant", "content": "Đó là", "stopped": True},
        ],
    }
    other = await call(app, "GET", "/api/v1/chat/sessions/s1/transcript", headers=auth_headers(sub="someone-else"))
    assert other.json()["messages"] == []


@pytest.mark.parametrize("session_id", ["a:b", "x" * 65, "space here"])
async def test_a_session_id_outside_the_safe_alphabet_is_refused(app, session_id):
    response = await call(app, "GET", f"/api/v1/chat/sessions/{session_id}/messages")

    assert response.status_code == 422
