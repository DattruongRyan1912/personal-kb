"""Postgres-only behaviour of the memory stores (PoC-A2, #297): indexes, foreign keys and the errors callers see."""

import traceback
from datetime import UTC, datetime

import asyncpg
import pytest

from personal_kb.core.exceptions import DependencyUnavailableError
from personal_kb.infrastructure.postgres.pg_graph_store import PgGraphStore, like_patterns, neighborhoods_sql
from personal_kb.infrastructure.postgres.pg_vector_store import PgVectorStore
from personal_kb.infrastructure.postgres.pool import create_pool, postgres_unavailable
from personal_kb.services.graph_models import Edge, GraphExtraction, Node
from personal_kb.services.provenance import SourceRevision
from tests.conftest import make_settings

T1 = datetime(2026, 10, 1, tzinfo=UTC)
LOGIN = GraphExtraction(
    nodes=[Node(id="feature:login", label="Feature"), Node(id="db_table:users", label="Database_Table")],
    edges=[Edge(source_id="feature:login", target_id="db_table:users", relation_type="MODIFIES")],
)


async def graph_with_login(pg_pool, pg_schema) -> PgGraphStore:
    store = PgGraphStore(pg_pool, schema=pg_schema, dimensions=4)
    await store.ensure()
    await store.apply_revision(
        SourceRevision("SPC-1", "1", "hash"), added={"k1": LOGIN}, removed=set(), kept=set(), observed_at=T1
    )
    return store


async def test_the_assertions_of_a_fact_are_found_by_index_at_any_time(pg_pool, pg_schema):
    # the open-only partial indexes cannot serve a past time: without a full index every assertion row is scanned
    await graph_with_login(pg_pool, pg_schema)

    async with pg_pool.acquire() as connection, connection.transaction():
        await connection.execute("SET LOCAL enable_seqscan = off")
        rows = await connection.fetch(
            "EXPLAIN " + neighborhoods_sql(pg_schema, at_time=True), like_patterns(["login"]), 10, T1
        )
    plan = "\n".join(r[0] for r in rows)

    assert "Seq Scan on entity_assertions" not in plan
    assert "Seq Scan on relation_assertions" not in plan


async def test_an_entity_still_asserted_cannot_be_deleted_under_its_assertions(pg_pool, pg_schema):
    # no cascade: a delete racing a revision of another source fails loudly instead of dropping that source's rows
    await graph_with_login(pg_pool, pg_schema)

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await pg_pool.execute(f"DELETE FROM {pg_schema}.relations")
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await pg_pool.execute(f"DELETE FROM {pg_schema}.entities WHERE id = 'db_table:users'")


async def test_a_search_before_init_db_says_to_run_it(pg_pool, pg_schema):
    with pytest.raises(DependencyUnavailableError, match="init-db"):
        await PgVectorStore(pg_pool, schema=pg_schema, dimensions=4).search([1.0, 0.0, 0.0, 0.0], 5)
    with pytest.raises(DependencyUnavailableError, match="init-db"):
        await PgGraphStore(pg_pool, schema=pg_schema, dimensions=4).neighborhoods(["users"])


@pytest.mark.parametrize(
    "error",
    [asyncpg.AdminShutdownError, asyncpg.TooManyConnectionsError, asyncpg.InvalidPasswordError],
    ids=["server stopping", "too many connections", "password refused"],
)
async def test_postgres_stopping_full_or_refusing_is_unavailable(error):
    with pytest.raises(DependencyUnavailableError, match=error.__name__):
        async with postgres_unavailable():
            raise error("from the server")


async def test_a_password_with_url_characters_never_shows_in_the_error():
    # urlsplit takes "leakedhost", a piece of this password, for the host
    settings = make_settings(postgres_url="postgresql://u:pw@leakedhost/rest@127.0.0.1:9/db")

    with pytest.raises(DependencyUnavailableError) as raised:
        await create_pool(settings, schema="test_unreachable")

    shown = "".join(traceback.format_exception(raised.value))
    assert "leakedhost" not in shown and "rest" not in str(raised.value)
