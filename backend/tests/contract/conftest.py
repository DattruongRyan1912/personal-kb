"""Fixtures for the contract of the memory ports (services/memory_ports.py), on Postgres + pgvector."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from personal_kb.infrastructure.postgres.pg_document_store import PgDocumentStore
from personal_kb.infrastructure.postgres.pg_graph_store import PgGraphStore
from personal_kb.infrastructure.postgres.pg_vector_store import PgVectorStore
from tests.contract.graph_probes import SqlProbe

DIMENSIONS = 4
T1 = datetime(2026, 10, 1, tzinfo=UTC)
T2 = T1 + timedelta(days=1)
T3 = T2 + timedelta(days=1)


class FakeEmbedder:
    """Deterministic 4-dimensional vectors; records the size of every batch."""

    def __init__(self):
        self.batches: list[int] = []

    async def embed(self, texts):
        self.batches.append(len(texts))
        return [[float(len(t)), 1.0, 0.5, 0.25] for t in texts]


class DownEmbedder:
    async def embed(self, texts):
        raise RuntimeError("embedding service down")


@pytest.fixture
async def vector_store(pg_pool, pg_schema):
    """A fresh, ensured vector store of 4-dimensional vectors."""
    store = PgVectorStore(pg_pool, schema=pg_schema, dimensions=DIMENSIONS)
    await store.ensure()
    return store


@pytest.fixture
def postgres_vector_store(vector_store):
    return vector_store


@pytest.fixture
async def document_store(pg_pool, pg_schema):
    """A fresh, ensured document store."""
    store = PgDocumentStore(pg_pool, schema=pg_schema, dimensions=DIMENSIONS)
    await store.ensure()
    return store


@pytest.fixture
def tag() -> str:
    """A unique marker for a graph test's ids: kept for the graph tests' fact ids."""
    return f"t{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def graph_backend(pg_pool, pg_schema):
    """(store, probe) on Postgres."""
    store = PgGraphStore(pg_pool, schema=pg_schema, dimensions=DIMENSIONS)
    await store.ensure()
    return store, SqlProbe(pg_pool)


@pytest.fixture
def graph_store(graph_backend):
    return graph_backend[0]


@pytest.fixture
def graph_probe(graph_backend):
    return graph_backend[1]
