import pytest

from personal_kb.core.exceptions import DependencyUnavailableError
from personal_kb.infrastructure import memory_backend
from personal_kb.infrastructure.memory_backend import build_memory
from personal_kb.infrastructure.postgres.pg_document_store import PgDocumentStore
from personal_kb.infrastructure.postgres.pg_graph_store import PgGraphStore
from personal_kb.infrastructure.postgres.pg_vector_store import PgVectorStore
from personal_kb.infrastructure.postgres.pg_worklog_store import PgWorklogStore
from tests.conftest import make_settings


class FakePool:
    def __init__(self):
        self.closed = False

    async def fetchval(self, query, *args):
        return 1

    async def close(self):
        self.closed = True


async def test_every_store_is_on_one_pool_made_on_first_use(monkeypatch):
    made = []

    async def create_pool(settings, *, schema=None):
        made.append(FakePool())
        return made[-1]

    monkeypatch.setattr(memory_backend, "create_pool", create_pool)
    settings = make_settings(postgres_url="postgresql://u:p@127.0.0.1:9/db")

    async with build_memory(settings) as stores:
        assert isinstance(stores.vectors, PgVectorStore)
        assert isinstance(stores.graph, PgGraphStore)
        assert isinstance(stores.documents, PgDocumentStore)
        assert isinstance(stores.worklog, PgWorklogStore)
        assert stores.vectors._pool is stores.graph._pool is stores.documents._pool is stores.pg
        assert made == []  # nothing connects until first use
        await stores.pg.fetchval("SELECT 1")
        await stores.pg.fetchval("SELECT 1")
        assert len(made) == 1
    assert made[0].closed


async def test_the_app_starts_while_postgres_is_down_and_a_search_says_so():
    settings = make_settings(postgres_url="postgresql://u:s3cret-pass@127.0.0.1:9/db")

    async with build_memory(settings) as stores:
        with pytest.raises(DependencyUnavailableError, match="postgres") as raised:
            await stores.vectors.search([1.0, 0.0, 0.0, 0.0], 5)
        with pytest.raises(DependencyUnavailableError, match="postgres"):
            await stores.graph.neighborhoods(["users"])

    assert "s3cret-pass" not in str(raised.value)
