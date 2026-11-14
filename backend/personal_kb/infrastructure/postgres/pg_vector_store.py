"""The VectorStore port on Postgres + pgvector (PoC-A2, #297), spec sections 6.1, 6.4 and 6.5.

A chunk version is a row of `chunks`; a revision closes the removed ones (`valid_to` set; the row stays, for questions
about the past). A revision writes in one transaction, under a lock per source: two runs of the same spec wait for each
other and leave one open row per key. A search filters by validity inside the HNSW scan (iterative scan), so closed
rows never crowd out the `limit` hits.
"""

import logging
import re
from datetime import datetime

from personal_kb.infrastructure.postgres.pool import PoolLike, postgres_unavailable
from personal_kb.infrastructure.postgres.schema import ensure_schema
from personal_kb.services.memory_ports import ChunkHit, EmbeddedChunk, VectorRevisionResult
from personal_kb.services.provenance import SourceRevision

log = logging.getLogger(__name__)

# websearch exclusions: -"a phrase" (closed or not) or a -word starting a token ("on-demand" is not one)
_EXCLUDED = re.compile(r'-"[^"]*"?|(?<!\S)-\S+')

EF_SEARCH = 100  # pgvector's hnsw.ef_search; Qdrant's hnsw_ef default is 128 (the scale bench records both)

# VALID(t): valid_from <= t < valid_to, or open now; the same rule as Qdrant's validity_filter and Neo4j's _VALID
_VALID_NOW = "valid_to IS NULL"
_VALID_AT = "valid_from <= $3 AND (valid_to IS NULL OR valid_to > $3)"


SEARCH_SETTINGS = f"SET LOCAL hnsw.iterative_scan = relaxed_order; SET LOCAL hnsw.ef_search = {EF_SEARCH}"


def _where(*, at_time: bool, project_filter: bool) -> str:
    """Validity now or at $3, and the project (last parameter) whatever its case: 'mynotch' is MyNotch."""
    where_valid = _VALID_AT if at_time else _VALID_NOW
    if not project_filter:
        return where_valid
    return f"{where_valid} AND lower(project_id) = lower({'$4' if at_time else '$3'})"


def search_sql(table: str, *, at_time: bool, project_filter: bool = False) -> str:
    """The k-nearest chunks valid now ($1 vector, $2 limit) or at $3, under SEARCH_SETTINGS (spec 6.4)."""
    # relaxed_order may return the nearest rows slightly out of order: they are sorted again outside the scan
    where_clause = _where(at_time=at_time, project_filter=project_filter)
    return (
        "WITH nearest AS MATERIALIZED ("
        " SELECT spec_id, chunk_key, valid_from, headings, content, revision, project_id,"
        "  embedding <=> $1::vector AS distance"
        f" FROM {table} WHERE {where_clause} ORDER BY embedding <=> $1::vector LIMIT $2"
        ") SELECT *, 1 - distance AS score FROM nearest ORDER BY distance"
    )


def fts_search_sql(table: str, *, at_time: bool, project_filter: bool = False, any_word: bool = False) -> str:
    """Full-text keyword search over tsv column valid now ($1 query, $2 limit) or at $3.

    Accents are ignored on both sides (kb_unaccent). Every word must match; with `any_word` one is enough, ranked by
    how many match and how close together they are."""
    schema = table.rpartition(".")[0]
    words = f"websearch_to_tsquery('simple', {schema}.kb_unaccent($1))"
    query = f"replace({words}::text, ' & ', ' | ')::tsquery" if any_word else words
    return (
        f"WITH q AS (SELECT {query} AS query) "
        "SELECT spec_id, chunk_key, valid_from, headings, content, revision, project_id, "
        " ts_rank_cd(tsv, q.query) AS score "
        f"FROM {table}, q "
        f"WHERE {_where(at_time=at_time, project_filter=project_filter)} AND tsv @@ q.query "
        "ORDER BY score DESC LIMIT $2"
    )


class PgVectorStore:
    def __init__(self, pool: PoolLike, *, schema: str, dimensions: int) -> None:
        self._pool = pool
        self._schema = schema
        self._dimensions = dimensions
        self._chunks = f"{schema}.chunks"

    async def ensure(self) -> bool:
        return await ensure_schema(self._pool, schema=self._schema, dimensions=self._dimensions)

    async def known_chunk_keys(self, source_id: str) -> set[str]:
        async with postgres_unavailable():
            rows = await self._pool.fetch(
                f"SELECT chunk_key FROM {self._chunks} WHERE spec_id = $1 AND valid_to IS NULL", source_id
            )
        return {r["chunk_key"] for r in rows}

    async def apply_revision(
        self, source: SourceRevision, *, added: list[EmbeddedChunk], removed: set[str], observed_at: datetime
    ) -> VectorRevisionResult:
        spec_id = source.source_id
        async with postgres_unavailable(), self._pool.acquire() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext('vector:' || $1))", spec_id)
            # under the lock the open keys cannot change: a key another run already wrote is not written twice
            already_open = {
                r["chunk_key"]
                for r in await connection.fetch(
                    f"SELECT chunk_key FROM {self._chunks} "
                    "WHERE spec_id = $1 AND valid_to IS NULL AND chunk_key = ANY($2::text[])",
                    spec_id,
                    [e.key for e in added],
                )
            }
            rows = [
                (
                    spec_id,
                    e.key,
                    source.revision,
                    e.chunk.headings,
                    e.chunk.content,
                    e.chunk.status,
                    e.chunk.chunk_index,
                    e.vector,
                    observed_at,
                    getattr(e.chunk, "project_id", "Personal-KB") or "Personal-KB",
                )
                for e in added
                if e.key not in already_open
            ]
            await connection.executemany(
                f"INSERT INTO {self._chunks} "
                "(spec_id, chunk_key, revision, headings, content, status, chunk_index, embedding, valid_from, "
                "project_id) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
                "ON CONFLICT (spec_id, chunk_key) WHERE valid_to IS NULL DO NOTHING",
                rows,
            )
            closed = await connection.fetchval(
                f"WITH closed AS (UPDATE {self._chunks} SET valid_to = $3 "
                "WHERE spec_id = $1 AND chunk_key = ANY($2::text[]) AND valid_to IS NULL RETURNING 1) "
                "SELECT count(*) FROM closed",
                spec_id,
                sorted(removed),
                observed_at,
            )
        return VectorRevisionResult(added=len(rows), closed=closed)

    async def set_project(self, source_id: str, project_id: str) -> int:
        """The spec's open chunks under `project_id`; an unchanged chunk is never written again, so a spec that moved
        to another project would otherwise keep the old one. Returns the chunks moved."""
        async with postgres_unavailable():
            return await self._pool.fetchval(
                f"WITH moved AS (UPDATE {self._chunks} SET project_id = $2 "
                "WHERE spec_id = $1 AND valid_to IS NULL AND project_id <> $2 RETURNING 1) SELECT count(*) FROM moved",
                source_id,
                project_id,
            )

    async def revision(self) -> str:
        """Changes whenever a chunk is written, closed, deleted or moved to another project: a search cached under
        it cannot outlive the chunks it was ranked from."""
        async with postgres_unavailable():
            row = await self._pool.fetchrow(
                "SELECT count(*), coalesce(max(id), 0), max(valid_to), "
                f"coalesce(sum(hashtext(project_id)) FILTER (WHERE valid_to IS NULL), 0) FROM {self._chunks}"
            )
        return ":".join(str(v) for v in row.values())

    async def delete_source(self, source_id: str) -> int:
        """Every row of the spec, closed ones included: a deleted source leaves nothing behind."""
        async with postgres_unavailable():
            return await self._pool.fetchval(
                f"WITH gone AS (DELETE FROM {self._chunks} WHERE spec_id = $1 RETURNING 1) SELECT count(*) FROM gone",
                source_id,
            )

    async def search(
        self,
        vector: list[float],
        limit: int,
        as_of: datetime | None = None,
        project_id: str | None = None,
    ) -> list[ChunkHit]:
        has_proj = bool(project_id and project_id.strip())
        query = search_sql(self._chunks, at_time=as_of is not None, project_filter=has_proj)
        args: list = [vector, limit]
        if as_of is not None:
            args.append(as_of)
        if has_proj:
            args.append(project_id.strip())
        async with postgres_unavailable(), self._pool.acquire() as connection, connection.transaction():
            await connection.execute(SEARCH_SETTINGS)  # SET LOCAL needs the transaction: asyncpg runs in autocommit
            rows = await connection.fetch(query, *args)
        return [
            ChunkHit(
                spec_id=r["spec_id"],
                chunk_key=r["chunk_key"],
                valid_from=r["valid_from"],
                headings=list(r["headings"]),
                content=r["content"],
                revision=r["revision"],
                score=float(r["score"]),
                project_id=r["project_id"] if "project_id" in r else "Personal-KB",
            )
            for r in rows
        ]

    async def search_fts(
        self,
        query: str,
        limit: int,
        as_of: datetime | None = None,
        project_id: str | None = None,
    ) -> list[ChunkHit]:
        """Full-text keyword search over tsv column with rank score (websearch_to_tsquery)."""
        # a query of exclusions only ("-phép") means "not phép": it would match every chunk without the word
        wanted = " ".join(_EXCLUDED.sub(" ", query or "").split())
        if not re.search(r"\w", wanted):
            return []

        has_proj = bool(project_id and project_id.strip())
        args: list = [query.strip(), limit]
        if as_of is not None:
            args.append(as_of)
        if has_proj:
            args.append(project_id.strip())
        try:
            async with postgres_unavailable(), self._pool.acquire() as connection:
                # a question in prose rarely has all its words in one chunk: then any of them will do
                for any_word in (False, True):
                    if any_word:
                        # an excluded word ("-phép") would become "or not phép" and match nearly every chunk
                        args[0] = wanted
                    sql = fts_search_sql(
                        self._chunks, at_time=as_of is not None, project_filter=has_proj, any_word=any_word
                    )
                    if rows := await connection.fetch(sql, *args):
                        break
            return [
                ChunkHit(
                    spec_id=r["spec_id"],
                    chunk_key=r["chunk_key"],
                    valid_from=r["valid_from"],
                    headings=list(r["headings"]),
                    content=r["content"],
                    revision=r["revision"],
                    score=float(r["score"]),
                    project_id=r["project_id"] if "project_id" in r else "Personal-KB",
                )
                for r in rows
            ]
        except Exception as exc:
            log.warning("[PgVectorStore] search_fts failed: %s", exc)
            return []
