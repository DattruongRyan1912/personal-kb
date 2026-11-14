"""The memory stores: chunks, documents, graph and worklog in one Postgres with pgvector (decision B4).

The rest of the app sees only the ports of services/memory_ports.py.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from personal_kb.core.config import Settings
from personal_kb.infrastructure.postgres.pg_document_store import PgDocumentStore
from personal_kb.infrastructure.postgres.pg_graph_store import PgGraphStore
from personal_kb.infrastructure.postgres.pg_vector_store import PgVectorStore
from personal_kb.infrastructure.postgres.pg_worklog_store import PgWorklogStore
from personal_kb.infrastructure.postgres.pool import LazyPool, create_pool
from personal_kb.services.memory_ports import DocumentStore, GraphStore, VectorStore
from personal_kb.services.worklog import WorklogStore


@dataclass(frozen=True)
class MemoryStores:
    vectors: VectorStore
    graph: GraphStore
    documents: DocumentStore
    worklog: WorklogStore
    pg: LazyPool  # the raw pool, for the Data Hub's statistics


@asynccontextmanager
async def build_memory(settings: Settings) -> AsyncIterator[MemoryStores]:
    """One pool, created on first use and closed on exit, shared by every store."""
    pool = LazyPool(lambda: create_pool(settings))
    store_args = {"schema": settings.postgres_schema, "dimensions": settings.embedding_dimensions}
    try:
        yield MemoryStores(
            vectors=PgVectorStore(pool, **store_args),
            graph=PgGraphStore(pool, **store_args),
            documents=PgDocumentStore(pool, **store_args),
            worklog=PgWorklogStore(pool, **store_args),
            pg=pool,
        )
    finally:
        await pool.close()
