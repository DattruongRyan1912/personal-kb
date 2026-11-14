"""Reading the graph store's facts back for the graph contract (PoC-A2, #297).

Postgres keeps one row per assertion, each with its own interval; the probe reports the intervals during which the
fact held: the union of its assertions' intervals, touching ones joined.
"""

from datetime import datetime
from typing import Protocol

Interval = tuple[datetime, datetime | None]

# VALID(t): valid now (no valid_to), or at $as_of: valid_from <= $as_of < valid_to
_CYPHER_VALID = (
    "(($as_of IS NULL AND {v}.valid_to IS NULL) OR "
    "($as_of IS NOT NULL AND {v}.valid_from <= $as_of AND ({v}.valid_to IS NULL OR {v}.valid_to > $as_of)))"
)
_SQL_VALID = (
    "(($2::timestamptz IS NULL AND valid_to IS NULL) OR "
    "($2 IS NOT NULL AND valid_from <= $2 AND (valid_to IS NULL OR valid_to > $2)))"
)


class GraphProbe(Protocol):
    async def intervals(self, src_id: str, rel_type: str, dst_id: str) -> list[Interval]: ...

    async def node_spec_ids(self, node_id: str, as_of: datetime | None = None) -> list[str]: ...

    async def relation_spec_ids(
        self, src_id: str, rel_type: str, dst_id: str, as_of: datetime | None = None
    ) -> list[str]: ...

    async def relation_asserted_by(self, src_id: str, rel_type: str, dst_id: str) -> list[str]: ...

    async def counts(self, tag: str) -> tuple[int, int]: ...

    async def mentions(self, source_id: str) -> int: ...  # nodes, relations or sources that still name it, any time


class SqlProbe:
    """On a pool whose search_path is the store's schema."""

    def __init__(self, pool) -> None:
        self._pool = pool

    async def intervals(self, src_id: str, rel_type: str, dst_id: str) -> list[Interval]:
        rows = await self._pool.fetch(
            "SELECT a.valid_from, a.valid_to FROM relation_assertions a JOIN relations r ON r.id = a.relation_id "
            "WHERE r.src = $1 AND r.type = $2 AND r.dst = $3 ORDER BY a.valid_from",
            src_id,
            rel_type,
            dst_id,
        )
        merged: list[Interval] = []
        for start, end in ((r["valid_from"], r["valid_to"]) for r in rows):
            if merged and (merged[-1][1] is None or start <= merged[-1][1]):
                last_start, last_end = merged[-1]
                merged[-1] = (last_start, None if last_end is None or end is None else max(last_end, end))
            else:
                merged.append((start, end))
        return merged

    async def node_spec_ids(self, node_id: str, as_of: datetime | None = None) -> list[str]:
        rows = await self._pool.fetch(
            f"SELECT DISTINCT source_id FROM entity_assertions WHERE entity_id = $1 AND {_SQL_VALID} ORDER BY 1",
            node_id,
            as_of,
        )
        return [r["source_id"] for r in rows]

    async def relation_spec_ids(
        self, src_id: str, rel_type: str, dst_id: str, as_of: datetime | None = None
    ) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT DISTINCT source_id FROM relation_assertions "
            "WHERE relation_id = (SELECT id FROM relations WHERE src = $1 AND type = $3 AND dst = $4) "
            f"AND {_SQL_VALID} ORDER BY 1",
            src_id,
            as_of,
            rel_type,
            dst_id,
        )
        return [r["source_id"] for r in rows]

    async def relation_asserted_by(self, src_id: str, rel_type: str, dst_id: str) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT a.source_id || '#' || a.chunk_key AS by FROM relation_assertions a "
            "JOIN relations r ON r.id = a.relation_id "
            "WHERE r.src = $1 AND r.type = $2 AND r.dst = $3 AND a.valid_to IS NULL ORDER BY 1",
            src_id,
            rel_type,
            dst_id,
        )
        return [r["by"] for r in rows]

    async def counts(self, tag: str) -> tuple[int, int]:
        row = await self._pool.fetchrow(
            "SELECT (SELECT count(*) FROM entities WHERE strpos(id, $1) > 0) AS nodes, "
            "(SELECT count(*) FROM relations WHERE strpos(src, $1) > 0) AS rels",
            tag,
        )
        return row["nodes"], row["rels"]

    async def mentions(self, source_id: str) -> int:
        return await self._pool.fetchval(
            "SELECT (SELECT count(*) FROM entity_assertions WHERE source_id = $1) "
            "+ (SELECT count(*) FROM relation_assertions WHERE source_id = $1) "
            "+ (SELECT count(*) FROM graph_sources WHERE id = $1)",
            source_id,
        )
