import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from personal_kb.core.auth import SupabaseJwtVerifier
from personal_kb.main import create_app
from tests.conftest import JWT_SECRET, make_settings

LOCAL = "http://localhost:54321"


async def post_token(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/v1/dev/token")


async def test_dev_login_is_off_by_default():
    assert (await post_token(create_app(make_settings()))).status_code == 404


async def test_dev_login_mints_a_token_the_api_accepts():
    app = create_app(make_settings(supabase_url=LOCAL, dev_login=True))

    response = await post_token(app)

    assert response.status_code == 200
    body = response.json()
    user = await SupabaseJwtVerifier(supabase_url=LOCAL, jwt_secret=JWT_SECRET).verify(body["access_token"])
    assert user.email == "dev@example.com" and body["expires_in"] == 3600


@pytest.mark.parametrize(
    "overrides",
    [{"supabase_url": "https://project.supabase.co"}, {"supabase_url": LOCAL, "supabase_jwt_secret": None}],
)
def test_dev_login_is_refused_outside_a_local_supabase(overrides):
    with pytest.raises(ValidationError, match="DEV_LOGIN"):
        make_settings(dev_login=True, **overrides)


async def test_cors_lets_the_chat_ui_call_the_api():
    app = create_app(make_settings(cors_origins="http://localhost:3001, http://127.0.0.1:3001"))
    headers = {"Origin": "http://localhost:3001", "Access-Control-Request-Method": "POST"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        allowed = await client.options(
            "/api/v1/chat/stream", headers=headers | {"Access-Control-Request-Headers": "authorization"}
        )
        other = await client.options("/api/v1/chat/stream", headers=headers | {"Origin": "https://evil.example"})

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3001"
    assert "access-control-allow-origin" not in other.headers
