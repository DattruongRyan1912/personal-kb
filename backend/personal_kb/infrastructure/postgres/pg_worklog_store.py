"""The WorklogStore port on Postgres: an append-only progress log (agent continuity)."""

import asyncio

from personal_kb.infrastructure.postgres.pool import PoolLike, postgres_unavailable
from personal_kb.infrastructure.postgres.schema import ensure_schema
from personal_kb.services.worklog import NewWorklogEntry, WorklogEntry

_COLUMNS = "id, project, kind, summary, next_steps, agent, session_id, branch, created_at"


class WorklogRestoreConflict(Exception):
    """Backed-up ids already hold other entries (written after a reset, before the restore): nothing was restored."""


class PgWorklogStore:
    def __init__(self, pool: PoolLike, *, schema: str, dimensions: int) -> None:
        self._pool = pool
        self._schema = schema
        self._dimensions = dimensions
        self._table = f"{schema}.worklog_entries"
        self._ready = False
        self._lock = asyncio.Lock()

    async def ensure(self) -> None:
        await ensure_schema(self._pool, schema=self._schema, dimensions=self._dimensions)

    async def _ensure_once(self) -> None:
        # nothing creates the tables at app or MCP startup, so the first use does it
        if self._ready:
            return
        async with self._lock:
            if not self._ready:
                await self.ensure()
                self._ready = True

    async def add(self, entry: NewWorklogEntry) -> WorklogEntry:
        await self._ensure_once()
        async with postgres_unavailable():
            row = await self._pool.fetchrow(
                f"INSERT INTO {self._table} (project, kind, summary, next_steps, agent, session_id, branch) "
                f"VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING {_COLUMNS}",
                entry.project,
                entry.kind,
                entry.summary,
                entry.next_steps,
                entry.agent,
                entry.session_id,
                entry.branch,
            )
        return _entry(row)

    async def recent(self, project: str = "", *, limit: int = 10, kind: str = "") -> list[WorklogEntry]:
        await self._ensure_once()
        async with postgres_unavailable():
            rows = await self._pool.fetch(
                f"SELECT {_COLUMNS} FROM {self._table} WHERE ($1 = '' OR project = $1) AND ($2 = '' OR kind = $2) "
                "ORDER BY created_at DESC, id DESC LIMIT $3",
                project,
                kind,
                limit,
            )
        return [_entry(r) for r in rows]

    async def all_entries(self) -> list[WorklogEntry]:
        """Every entry, oldest first: the backup of the one table not rebuilt from knowledge/."""
        await self._ensure_once()
        async with postgres_unavailable():
            rows = await self._pool.fetch(f"SELECT {_COLUMNS} FROM {self._table} ORDER BY id")
        return [_entry(r) for r in rows]

    async def restore(self, entries: list[WorklogEntry]) -> int:
        """Insert backed-up entries with their ids and times. An id already holding the same entry (same time and
        project) is skipped; one holding another entry stops the restore (WorklogRestoreConflict) rather than dropping
        the backed-up one.
        Returns rows added."""
        await self._ensure_once()
        present = {
            e.id: e
            for e in map(
                _entry,
                await self._pool.fetch(
                    f"SELECT {_COLUMNS} FROM {self._table} WHERE id = ANY($1::bigint[])", [e.id for e in entries]
                ),
            )
        }
        # the same entry has the same id, time and project; its text may differ only by the backup's secret masking
        clashes = sorted(
            e.id
            for e in entries
            if e.id in present and (present[e.id].created_at, present[e.id].project) != (e.created_at, e.project)
        )
        if clashes:
            raise WorklogRestoreConflict(
                f"ids {clashes} already hold other entries: restore into an empty worklog_entries table"
            )
        columns = ("id", "project", "kind", "summary", "next_steps", "agent", "session_id", "branch", "created_at")
        types = ("bigint", "text", "text", "text", "text", "text", "text", "text", "timestamptz")
        arrays = [[getattr(e, c) for e in entries] for c in columns]
        unnest = ", ".join(f"${i}::{t}[]" for i, t in enumerate(types, 1))
        async with postgres_unavailable(), self._pool.acquire() as connection, connection.transaction():
            added = await connection.fetchval(
                f"WITH added AS (INSERT INTO {self._table} ({', '.join(columns)}) SELECT * FROM unnest({unnest}) "
                "ON CONFLICT (id) DO NOTHING RETURNING 1) SELECT count(*) FROM added",
                *arrays,
            )
            # the next add() must not reuse a restored id
            await connection.execute(
                f"SELECT setval(pg_get_serial_sequence('{self._table}', 'id'), "
                f"GREATEST((SELECT max(id) FROM {self._table}), 1))"
            )
        return added


def _entry(row) -> WorklogEntry:
    return WorklogEntry(
        id=row["id"],
        project=row["project"],
        kind=row["kind"],
        summary=row["summary"],
        next_steps=row["next_steps"],
        agent=row["agent"],
        session_id=row["session_id"],
        branch=row["branch"],
        created_at=row["created_at"],
    )
