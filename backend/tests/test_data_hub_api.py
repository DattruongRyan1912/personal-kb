"""The Data Hub (/api/v1/data): signed-in only, and what its catalog, chunks, audit and delete report on Postgres."""

import pytest
from httpx import ASGITransport, AsyncClient

from personal_kb.api import data_hub
from personal_kb.infrastructure.memory_backend import MemoryStores
from personal_kb.infrastructure.postgres.pg_document_store import PgDocumentStore
from personal_kb.infrastructure.postgres.pg_graph_store import PgGraphStore
from personal_kb.infrastructure.postgres.pg_vector_store import PgVectorStore
from personal_kb.infrastructure.postgres.pg_worklog_store import PgWorklogStore
from personal_kb.main import create_app
from personal_kb.services.ingestion import ingest_documents
from tests.conftest import auth_headers, make_settings
from tests.contract.conftest import FakeEmbedder

DIMENSIONS = 4


@pytest.fixture
async def hub(pg_pool, pg_schema, tmp_path, monkeypatch):
    knowledge = tmp_path / "knowledge"
    (knowledge / "Demo-Core").mkdir(parents=True)
    (knowledge / "Demo-Core" / "HR-A.md").write_text(
        "---\nid: HR-A\ntitle: Nghỉ phép\n---\n# 1. A\nText a.\n# 2. B\nText b.\n"
    )
    (knowledge / "PKB-Z.md").write_text("---\nid: PKB-Z\ntitle: Chưa nạp\n---\n# Z\nText z.\n")
    monkeypatch.setattr(data_hub, "get_knowledge_dir", lambda: knowledge)
    args = {"schema": pg_schema, "dimensions": DIMENSIONS}
    stores = MemoryStores(
        vectors=PgVectorStore(pg_pool, **args),
        graph=PgGraphStore(pg_pool, **args),
        documents=PgDocumentStore(pg_pool, **args),
        worklog=PgWorklogStore(pg_pool, **args),
        pg=pg_pool,
    )
    await stores.vectors.ensure()
    await ingest_documents(
        [knowledge / "Demo-Core" / "HR-A.md"],
        embedder=FakeEmbedder(),
        vectors=stores.vectors,
        documents=stores.documents,
    )
    app = create_app(make_settings(postgres_schema=pg_schema, embedding_dimensions=DIMENSIONS))
    app.state.stores = stores
    return app, knowledge


async def call(app, method, path, headers=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, headers=auth_headers() if headers is None else headers)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/data/catalog"),
        ("GET", "/api/v1/data/topology"),
        ("POST", "/api/v1/data/audit"),
        ("GET", "/api/v1/data/documents/HR-A/chunks"),
        ("DELETE", "/api/v1/data/documents/HR-A"),
        ("POST", "/api/v1/data/reindex/HR-A"),
        ("POST", "/api/v1/data/upload"),
        ("POST", "/api/v1/data/sandbox/retrieve"),
    ],
)
async def test_every_data_hub_route_needs_a_signed_in_user(hub, method, path):
    # an upload is a CORS "simple request": without this, any page open in the browser could write to knowledge/
    app, knowledge = hub

    response = await call(app, method, path, headers={})

    assert response.status_code == 401
    assert (knowledge / "Demo-Core" / "HR-A.md").exists()


async def test_the_catalog_lists_files_with_their_project_and_chunk_count(hub):
    app, _ = hub

    body = (await call(app, "GET", "/api/v1/data/catalog")).json()

    items = {i["spec_id"]: i for i in body["items"]}
    assert items["HR-A"]["project_id"] == "Demo-Core" and items["HR-A"]["chunk_count"] == 2
    assert items["HR-A"]["title"] == "Nghỉ phép" and items["PKB-Z"]["chunk_count"] == 0
    assert body["storage_backend"] == "postgres"


async def test_the_chunks_of_a_spec_come_in_order(hub):
    app, _ = hub

    body = (await call(app, "GET", "/api/v1/data/documents/HR-A/chunks")).json()

    assert [c["chunk_index"] for c in body["chunks"]] == [0, 1] and body["total_chunks"] == 2


async def test_the_audit_finds_a_file_not_ingested(hub):
    app, _ = hub

    body = (await call(app, "POST", "/api/v1/data/audit")).json()

    assert body["missing_in_db"] == ["PKB-Z"] and body["orphan_in_db"] == [] and body["audit_passed"] is False


async def test_deleting_a_spec_removes_its_file_document_and_chunks(hub, pg_pool):
    app, knowledge = hub

    response = await call(app, "DELETE", "/api/v1/data/documents/HR-A")

    assert response.status_code == 200 and response.json()["file_deleted"] is True
    assert not (knowledge / "Demo-Core" / "HR-A.md").exists()
    assert await pg_pool.fetchval("SELECT count(*) FROM chunks WHERE spec_id = 'HR-A'") == 0
    assert await pg_pool.fetchval("SELECT count(*) FROM documents WHERE spec_id = 'HR-A'") == 0


async def test_a_file_named_differently_from_its_id_is_listed_and_audited_by_its_id(hub, pg_pool):
    # KB-01 lives in KB-01-huong-dan.md: the catalog showed it with 0 chunks and the audit as missing and orphan
    app, knowledge = hub
    (knowledge / "KB-01-huong-dan.md").write_text("---\nid: KB-01\ntitle: Hướng dẫn\n---\n# H\nText h.\n")
    stores = app.state.stores
    await ingest_documents([knowledge / "KB-01-huong-dan.md"], embedder=FakeEmbedder(), vectors=stores.vectors)

    catalog = {i["spec_id"]: i for i in (await call(app, "GET", "/api/v1/data/catalog")).json()["items"]}
    audit = (await call(app, "POST", "/api/v1/data/audit")).json()

    assert catalog["KB-01"]["chunk_count"] == 1 and "KB-01-huong-dan" not in catalog
    assert "KB-01" not in audit["missing_in_db"] and "KB-01" not in audit["orphan_in_db"]
