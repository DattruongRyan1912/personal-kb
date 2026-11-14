import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from personal_kb.api.chat import get_agent
from personal_kb.main import create_app
from tests.conftest import auth_headers, make_settings

ME = "7b1e0000-0000-4000-8000-000000000001"


class FakeAgent:
    def __init__(self):
        self.asked = []

    async def ask(self, user_id, session_id, text, ctx):
        self.asked.append((user_id, session_id, text))
        return AIMessage("Luồng thanh toán dùng VNPay [Luồng thanh toán](SPC-2).")

    async def stream(self, user_id, session_id, text, ctx):
        self.asked.append((user_id, session_id, text))
        yield {"type": "status", "message": "🤔 Đang phân tích câu hỏi..."}
        yield {"type": "text_delta", "delta": "Hệ "}
        yield {"type": "done"}


@pytest.fixture
def agent():
    return FakeAgent()


@pytest.fixture
def app(agent):
    app = create_app(make_settings())
    app.state.tool_context = None
    app.dependency_overrides[get_agent] = lambda: agent
    return app


async def post(app, body, headers=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/v1/chat", json=body, headers=auth_headers() if headers is None else headers)


async def test_chat_needs_a_signed_in_user(app):
    assert (await post(app, {"session_id": "s1", "message": "hi"}, headers={})).status_code == 401


async def test_chat_asks_the_agent_as_the_signed_in_user(app, agent):
    response = await post(app, {"session_id": "s1", "message": "  Luồng thanh toán thế nào?  "})

    assert response.status_code == 200
    assert response.json() == {"session_id": "s1", "answer": "Luồng thanh toán dùng VNPay [Luồng thanh toán](SPC-2)."}
    assert agent.asked == [(ME, "s1", "Luồng thanh toán thế nào?")]


@pytest.mark.parametrize("body", [{"session_id": "s1", "message": "   "}, {"session_id": "a:b", "message": "hi"}, {}])
async def test_bad_input_is_refused_with_422(app, agent, body):
    assert (await post(app, body)).status_code == 422
    assert agent.asked == []


class RedisDownAgent:
    async def ask(self, *args, **kwargs):
        from redis.exceptions import ConnectionError as RedisConnectionError

        raise RedisConnectionError("Error 111 connecting to memory-redis:6379. Connection refused.")


async def test_a_down_redis_is_a_503_not_a_500():
    app = create_app(make_settings())
    app.state.tool_context = None
    app.dependency_overrides[get_agent] = RedisDownAgent

    response = await post(app, {"session_id": "s1", "message": "Luồng thanh toán thế nào?"})

    assert response.status_code == 503
    assert response.json()["error"] == "REDIS_UNAVAILABLE"


async def test_the_stream_is_server_sent_events_for_the_signed_in_user(app, agent):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/stream", json={"session_id": "s1", "message": "hi"}, headers=auth_headers()
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.text.split("\n\n")[:2] == [
        'event: status\ndata: {"type": "status", "message": "🤔 Đang phân tích câu hỏi..."}',
        'event: text_delta\ndata: {"type": "text_delta", "delta": "Hệ "}',
    ]
    assert agent.asked == [(ME, "s1", "hi")]


async def test_the_stream_needs_a_signed_in_user(app, agent):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/stream", json={"session_id": "s1", "message": "hi"})

    assert response.status_code == 401 and agent.asked == []


async def test_an_effort_sent_by_an_older_chat_ui_is_ignored(app, agent):
    response = await post(app, {"session_id": "s1", "message": "hi", "effort": "high"})

    assert response.status_code == 200 and agent.asked == [(ME, "s1", "hi")]
