import pytest
from httpx import ASGITransport, AsyncClient

from personal_kb.infrastructure.memory_backend import MemoryStores
from personal_kb.infrastructure.postgres.pg_document_store import PgDocumentStore
from personal_kb.infrastructure.postgres.pg_graph_store import PgGraphStore
from personal_kb.infrastructure.postgres.pg_vector_store import PgVectorStore
from personal_kb.infrastructure.postgres.pg_worklog_store import PgWorklogStore
from personal_kb.infrastructure.postgres.pool import LazyPool, create_pool
from personal_kb.main import create_app
from tests.conftest import auth_headers, make_settings

DIMENSIONS = 1536  # the app's default EMBEDDING_DIMENSIONS


def settings():
    return make_settings()


def stores_on(pool, schema: str, dimensions: int = DIMENSIONS) -> MemoryStores:
    args = {"schema": schema, "dimensions": dimensions}
    return MemoryStores(
        vectors=PgVectorStore(pool, **args),
        graph=PgGraphStore(pool, **args),
        documents=PgDocumentStore(pool, **args),
        worklog=PgWorklogStore(pool, **args),
        pg=pool,
    )


@pytest.fixture
def offline_app():
    """An app whose stores point at a Postgres nobody listens on: enough for what never touches them."""
    app = create_app(settings())
    unreachable = make_settings(postgres_url="postgresql://u:p@127.0.0.1:9/db")
    app.state.stores = stores_on(LazyPool(lambda: create_pool(unreachable)), "public")
    return app


@pytest.fixture
def app(pg_pool, pg_schema):
    app = create_app(make_settings(postgres_schema=pg_schema))
    app.state.stores = stores_on(pg_pool, pg_schema)
    return app


async def request(app, method: str, path: str, headers=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, headers=auth_headers() if headers is None else headers)


async def test_init_db_needs_a_signed_in_user(offline_app):
    response = await request(offline_app, "POST", "/api/v1/system/init-db", headers={})

    assert response.status_code == 401
    assert response.json()["error"] == "UNAUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_init_db_creates_the_chunks_table_of_the_configured_size(app, pg_pool, pg_schema):
    response = await request(app, "POST", "/api/v1/system/init-db")

    assert response.status_code == 200
    assert response.json() == {"backend": "postgres", "collection": f"{pg_schema}.chunks", "created": True}
    column = await pg_pool.fetchval(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = to_regclass($1) AND attname = 'embedding'",
        f"{pg_schema}.chunks",
    )
    assert column == f"vector({DIMENSIONS})"


async def test_init_db_twice_keeps_the_existing_table(app, pg_schema):
    await request(app, "POST", "/api/v1/system/init-db")

    response = await request(app, "POST", "/api/v1/system/init-db")

    assert response.status_code == 200
    assert response.json() == {"backend": "postgres", "collection": f"{pg_schema}.chunks", "created": False}


async def test_init_db_reports_an_unreachable_postgres_as_503(offline_app):
    response = await request(offline_app, "POST", "/api/v1/system/init-db")

    assert response.status_code == 503
    assert response.json()["error"] == "POSTGRES_UNAVAILABLE"


async def test_init_db_refuses_an_existing_table_of_another_size(app, pg_pool, pg_schema):
    await stores_on(pg_pool, pg_schema, dimensions=1024).vectors.ensure()

    response = await request(app, "POST", "/api/v1/system/init-db")

    assert response.status_code == 409
    assert response.json()["error"] == "COLLECTION_MISMATCH"
    assert "1024" in response.json()["message"] and "1536" in response.json()["message"]


async def test_swagger_ui_is_served(offline_app):
    response = await request(offline_app, "GET", "/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_app_refuses_to_start_without_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(Exception, match="openai_api_key"):
        create_app()


def test_the_app_logs_its_own_info_messages():
    import logging

    create_app(settings())

    assert logging.getLogger("personal_kb.services.retrieval").isEnabledFor(logging.INFO)


def test_startup_logs_the_tools_as_an_openai_schema_array(caplog):
    import json
    import logging

    caplog.set_level(logging.INFO)

    app = create_app(settings())

    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("[ToolRegistry]"))
    schemas = json.loads(line.split(" ", 2)[2])
    assert {s["function"]["name"] for s in schemas} == set(app.state.tools.names)
    assert all(s["type"] == "function" for s in schemas)


async def test_health_answers_without_a_token_for_container_healthchecks(offline_app):
    response = await request(offline_app, "GET", "/health", headers={})

    assert response.status_code == 200 and response.json() == {"status": "ok"}
