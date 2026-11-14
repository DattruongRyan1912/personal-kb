"""The GraphStore port on Postgres (PoC-A2, #297), spec sections 5 and 6.2.

An entity or relation holds no time of its own: it is valid while at least one assertion row is, and each assertion
(fact, source, chunk) has its own interval. So a shared fact keeps every source's history apart, and deleting a source
leaves the fact valid exactly while the others stated it. A revision runs in one transaction under a lock per source;
it writes its new assertions before it closes those of removed chunks, so a fact that only moved never closes.
"""

import json
from datetime import datetime

import asyncpg

from personal_kb.infrastructure.postgres.pool import PoolLike, postgres_unavailable
from personal_kb.infrastructure.postgres.schema import ensure_schema
from personal_kb.services.graph_models import GraphExtraction
from personal_kb.services.graph_text import GraphFact, graph_fact
from personal_kb.services.memory_ports import DeleteResult, RevisionResult, StaleRevisionError
from personal_kb.services.provenance import SourceRevision

# VALID(t) over an assertion row `a`: open now, or valid_from <= t < valid_to (the rule of every store)
_VALID_NOW = "a.valid_to IS NULL"
_VALID_AT = "a.valid_from <= $3 AND (a.valid_to IS NULL OR a.valid_to > $3)"

# Entities whose name contains a term (most terms first), each with its one-hop links, as Neo4jService returns them:
# outgoing links first, then by type and the other end's id; spec_ids are the sources whose assertions hold at t.
_NEIGHBORHOODS = """
WITH matched AS (
    SELECT e.id, e.label, e.name,
        (SELECT count(*) FROM unnest($1::text[]) AS p(pattern) WHERE e.name LIKE p.pattern) AS hits
    FROM {s}.entities e
    WHERE e.name LIKE ANY($1::text[])
      AND EXISTS (SELECT 1 FROM {s}.entity_assertions a WHERE a.entity_id = e.id AND {valid})
    ORDER BY hits DESC, e.id
    LIMIT $2
)
SELECT n.id, n.label, n.name, n.hits,
    ARRAY(SELECT DISTINCT a.source_id FROM {s}.entity_assertions a WHERE a.entity_id = n.id AND {valid} ORDER BY 1)
        AS spec_ids,
    (SELECT coalesce(json_agg(json_build_object(
            'type', l.type, 'outgoing', l.outgoing, 'other_label', l.other_label, 'other_name', l.other_name,
            'spec_ids', l.spec_ids) ORDER BY l.outgoing DESC, l.type, l.other_id), '[]')
     FROM (
        SELECT r.type, r.src = n.id AS outgoing, m.id AS other_id, m.label AS other_label, m.name AS other_name,
            ARRAY(SELECT DISTINCT a.source_id FROM {s}.relation_assertions a
                  WHERE a.relation_id = r.id AND {valid} ORDER BY 1) AS spec_ids
        FROM {s}.relations r
        JOIN {s}.entities m ON m.id = CASE WHEN r.src = n.id THEN r.dst ELSE r.src END
        WHERE (r.src = n.id OR r.dst = n.id)
          AND EXISTS (SELECT 1 FROM {s}.relation_assertions a WHERE a.relation_id = r.id AND {valid})
     ) l) AS links
FROM matched n
ORDER BY n.hits DESC, n.id
"""


class PgGraphStore:
    def __init__(self, pool: PoolLike, *, schema: str, dimensions: int) -> None:
        self._pool = pool
        self._schema = schema
        self._dimensions = dimensions

    async def ensure(self) -> None:
        await ensure_schema(self._pool, schema=self._schema, dimensions=self._dimensions)

    async def known_chunk_keys(self, source_id: str) -> set[str]:
        async with postgres_unavailable():
            keys = await self._pool.fetchval(
                f"SELECT chunk_keys FROM {self._schema}.graph_sources WHERE id = $1", source_id
            )
        return set(keys or [])

    async def apply_revision(
        self,
        source: SourceRevision,
        *,
        added: dict[str, GraphExtraction],
        removed: set[str],
        kept: set[str],
        observed_at: datetime,
    ) -> RevisionResult:
        """One source revision in one transaction: new chunks asserted, then removed chunks retracted (spec 6.2)."""
        s, source_id = self._schema, source.source_id  # s prefixes every table name
        entities: dict[str, tuple[str, str]] = {}  # id -> (label, name)
        entity_keys: set[tuple[str, str]] = set()  # (entity id, chunk key)
        triples: set[tuple[str, str, str]] = set()
        relation_keys: set[tuple[str, str, str, str]] = set()  # (src, type, dst, chunk key)
        for key, extraction in added.items():
            for node in extraction.nodes:
                entities[node.id] = (node.label, node.id.split(":", 1)[1])
                entity_keys.add((node.id, key))
            for edge in extraction.edges:
                triple = (edge.source_id, edge.relation_type, edge.target_id)
                triples.add(triple)
                relation_keys.add((*triple, key))
        gone = sorted(removed)

        async with postgres_unavailable(), self._pool.acquire() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext('graph:' || $1))", source_id)
            # the plan was made from the chunk keys before a minutes-long extraction: kept ∪ removed is what it read.
            # Another run may have applied since. A key it removed, or one it added that this plan does not add too,
            # would leave stale facts open or close current ones for good; a key both add is the same chunk, re-asserted
            planned = kept | removed
            stored = set(
                await connection.fetchval(f"SELECT chunk_keys FROM {s}.graph_sources WHERE id = $1", source_id) or []
            )
            if not planned <= stored <= planned | added.keys():
                raise StaleRevisionError(f"{source_id}: its chunk keys changed since this revision was planned")
            # the relations this revision touches, and which of them hold now: opened/closed are counted over them only
            touched = await self._relation_ids(connection, triples) | {
                r["relation_id"]
                for r in await connection.fetch(
                    f"SELECT DISTINCT relation_id FROM {s}.relation_assertions "
                    "WHERE source_id = $1 AND chunk_key = ANY($2::text[]) AND valid_to IS NULL",
                    source_id,
                    gone,
                )
            }
            open_before = await self._open(connection, touched)

            if entities:
                ids = sorted(entities)
                await connection.execute(
                    f"INSERT INTO {s}.entities (id, label, name) "
                    "SELECT * FROM unnest($1::text[], $2::text[], $3::text[]) "
                    "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
                    ids,
                    [entities[i][0] for i in ids],
                    [entities[i][1] for i in ids],
                )
                pairs = sorted(entity_keys)
                await connection.execute(
                    f"INSERT INTO {s}.entity_assertions (entity_id, source_id, chunk_key, valid_from) "
                    "SELECT e, $3, k, $4 FROM unnest($1::text[], $2::text[]) AS t(e, k) "
                    "ON CONFLICT (entity_id, source_id, chunk_key) WHERE valid_to IS NULL DO NOTHING",
                    [e for e, _ in pairs],
                    [k for _, k in pairs],
                    source_id,
                    observed_at,
                )
            if triples:
                rows = sorted(triples)
                await connection.execute(
                    f"INSERT INTO {s}.relations (src, type, dst) "
                    "SELECT * FROM unnest($1::text[], $2::text[], $3::text[]) ON CONFLICT (src, type, dst) DO NOTHING",
                    [r[0] for r in rows],
                    [r[1] for r in rows],
                    [r[2] for r in rows],
                )
                stated = sorted(relation_keys)
                await connection.execute(
                    f"INSERT INTO {s}.relation_assertions (relation_id, source_id, chunk_key, valid_from) "
                    f"SELECT r.id, $5, t.k, $6 FROM unnest($1::text[], $2::text[], $3::text[], $4::text[]) "
                    f"AS t(src, type, dst, k) JOIN {s}.relations r USING (src, type, dst) "
                    "ON CONFLICT (relation_id, source_id, chunk_key) WHERE valid_to IS NULL DO NOTHING",
                    [r[0] for r in stated],
                    [r[1] for r in stated],
                    [r[2] for r in stated],
                    [r[3] for r in stated],
                    source_id,
                    observed_at,
                )
                touched |= await self._relation_ids(connection, triples)
            if gone:
                for table in ("entity_assertions", "relation_assertions"):
                    await connection.execute(
                        f"UPDATE {s}.{table} SET valid_to = $3 "
                        "WHERE source_id = $1 AND chunk_key = ANY($2::text[]) AND valid_to IS NULL",
                        source_id,
                        gone,
                        observed_at,
                    )
            open_after = await self._open(connection, touched)
            await connection.execute(
                f"INSERT INTO {s}.graph_sources (id, revision, content_hash, observed_at, chunk_keys) "
                "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO UPDATE SET revision = EXCLUDED.revision, "
                "content_hash = EXCLUDED.content_hash, observed_at = EXCLUDED.observed_at, "
                "chunk_keys = EXCLUDED.chunk_keys",
                source_id,
                source.revision,
                source.content_hash,
                observed_at,
                sorted(kept | added.keys()),
            )
        return RevisionResult(opened=len(open_after - open_before), closed=len(open_before - open_after))

    async def delete_source(self, source_id: str, *, observed_at: datetime) -> DeleteResult:
        """Forget a source, past included (spec 6.5): its assertions go, then the relations and entities nothing else
        asserts. A shared fact keeps only the other sources' intervals, so it holds exactly while they stated it.
        `observed_at` is unused: nothing needs closing, because validity lives in the assertions."""
        s = self._schema
        async with postgres_unavailable(), self._pool.acquire() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext('graph:' || $1))", source_id)
            entity_ids = await connection.fetch(
                f"DELETE FROM {s}.entity_assertions WHERE source_id = $1 RETURNING entity_id", source_id
            )
            relation_ids = await connection.fetch(
                f"DELETE FROM {s}.relation_assertions WHERE source_id = $1 RETURNING relation_id", source_id
            )
            relations = await connection.fetch(
                f"DELETE FROM {s}.relations r WHERE r.id = ANY($1::bigint[]) "
                f"AND NOT EXISTS (SELECT 1 FROM {s}.relation_assertions a WHERE a.relation_id = r.id) "
                "RETURNING r.src, r.dst",
                sorted({r["relation_id"] for r in relation_ids}),
            )
            candidates = {r["entity_id"] for r in entity_ids} | {e for r in relations for e in (r["src"], r["dst"])}
            nodes = await connection.fetchval(
                f"WITH gone AS (DELETE FROM {s}.entities e WHERE e.id = ANY($1::text[]) "
                f"AND NOT EXISTS (SELECT 1 FROM {s}.entity_assertions a WHERE a.entity_id = e.id) "
                f"AND NOT EXISTS (SELECT 1 FROM {s}.relations r WHERE r.src = e.id OR r.dst = e.id) "
                "RETURNING 1) SELECT count(*) FROM gone",
                sorted(candidates),
            )
            await connection.execute(f"DELETE FROM {s}.graph_sources WHERE id = $1", source_id)
        return DeleteResult(relationships=len(relations), nodes=nodes)

    async def neighborhoods(self, terms: list[str], limit: int = 10, as_of: datetime | None = None) -> list[GraphFact]:
        """Entities whose name contains any term (most terms first), each with its one-hop links (spec 6.3); only what
        holds now, or what held at `as_of`. A term matches literally, as Neo4j's CONTAINS does: `_` and `%` too."""
        if not terms:
            return []
        query = neighborhoods_sql(self._schema, at_time=as_of is not None)
        patterns = like_patterns(terms)
        args = (patterns, limit) if as_of is None else (patterns, limit, as_of)
        async with postgres_unavailable():
            rows = await self._pool.fetch(query, *args)
        return [graph_fact({**dict(r), "links": json.loads(r["links"])}) for r in rows]

    async def _relation_ids(self, connection: asyncpg.Connection, triples: set[tuple[str, str, str]]) -> set[int]:
        if not triples:
            return set()
        rows = sorted(triples)
        found = await connection.fetch(
            f"SELECT r.id FROM {self._schema}.relations r "
            "JOIN unnest($1::text[], $2::text[], $3::text[]) AS t(src, type, dst) USING (src, type, dst)",
            [r[0] for r in rows],
            [r[1] for r in rows],
            [r[2] for r in rows],
        )
        return {r["id"] for r in found}

    async def _open(self, connection: asyncpg.Connection, relation_ids: set[int]) -> set[int]:
        """The relations among `relation_ids` that at least one open assertion states."""
        if not relation_ids:
            return set()
        found = await connection.fetch(
            f"SELECT DISTINCT relation_id FROM {self._schema}.relation_assertions "
            "WHERE relation_id = ANY($1::bigint[]) AND valid_to IS NULL",
            sorted(relation_ids),
        )
        return {r["relation_id"] for r in found}


def neighborhoods_sql(schema: str, *, at_time: bool) -> str:
    """Entities matching the patterns ($1) with their links, at most $2, valid now or at $3 (spec 6.3)."""
    return _NEIGHBORHOODS.format(s=schema, valid=_VALID_AT if at_time else _VALID_NOW)


def like_patterns(terms: list[str]) -> list[str]:
    """Each term as a literal inside a LIKE pattern (backslash is LIKE's default escape), as Neo4j's CONTAINS."""
    return ["%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for t in terms]
