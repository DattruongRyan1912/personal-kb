"""Shared test helpers: settings for an app under test, Supabase user tokens it accepts, a Postgres schema per test."""

import os
import time
import uuid

# Disable OpenTelemetry and Langfuse background trace exporters during unit tests
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

import jwt
import pytest

from personal_kb.core.config import Settings
from personal_kb.core.exceptions import DependencyUnavailableError
from personal_kb.infrastructure.postgres.pool import create_pool

SUPABASE_URL = "https://project.supabase.co"
JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long!!"


# Variables the app reads from the environment. Tests build their settings explicitly, so values exported for a local
# run (`uv run --env-file ../.env pytest`, e.g. Ollama's OPENAI_BASE_URL) must not leak in. POSTGRES_URL stays: the
# Postgres integration tests use it.
_KEEP = {"POSTGRES_URL"}


@pytest.fixture(autouse=True)
def _isolate_app_settings(monkeypatch):
    for field in Settings.model_fields:
        if field.upper() not in _KEEP:
            monkeypatch.delenv(field.upper(), raising=False)


def make_settings(**overrides) -> Settings:
    values = {
        "openai_api_key": "sk-test",
        "postgres_url": "postgresql://unused:unused@unused:5432/unused",
        "reranker_url": "http://unused",
        "redis_url": "redis://unused:6379/0",
        "supabase_url": SUPABASE_URL,
        "supabase_jwt_secret": JWT_SECRET,
    } | overrides
    return Settings(_env_file=None, **values)


def user_token(**overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "7b1e0000-0000-4000-8000-000000000001",
        "aud": "authenticated",
        "iss": f"{SUPABASE_URL}/auth/v1",
        "exp": now + 3600,
    } | overrides
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def auth_headers(**overrides) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_token(**overrides)}"}


@pytest.fixture
def pg_schema() -> str:
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def pg_pool(pg_schema):
    """A pool on the Postgres of POSTGRES_URL whose search_path is a fresh schema, dropped afterwards (PoC-A2).

    Skips without POSTGRES_URL or a reachable server; POSTGRES_REQUIRED=1 turns that into a failure."""
    unavailable = pytest.fail if os.environ.get("POSTGRES_REQUIRED") == "1" else pytest.skip
    url = os.environ.get("POSTGRES_URL")
    if not url:
        unavailable("POSTGRES_URL not set")
    try:
        pool = await create_pool(make_settings(postgres_url=url), schema=pg_schema)
    except DependencyUnavailableError as exc:
        unavailable(str(exc))
    yield pool
    await pool.execute(f'DROP SCHEMA IF EXISTS "{pg_schema}" CASCADE')
    await pool.close()
