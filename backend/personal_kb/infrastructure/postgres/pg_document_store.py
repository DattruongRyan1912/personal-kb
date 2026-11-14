"""The DocumentStore port on Postgres: whole SDD documents by spec id (PoC-A2, #297)."""

from personal_kb.infrastructure.postgres.pool import PoolLike, postgres_unavailable
from personal_kb.infrastructure.postgres.schema import ensure_schema
from personal_kb.services.memory_ports import SpecDocument


class PgDocumentStore:
    def __init__(self, pool: PoolLike, *, schema: str, dimensions: int) -> None:
        self._pool = pool
        self._schema = schema
        self._dimensions = dimensions
        self._table = f"{schema}.documents"

    async def ensure(self) -> None:
        await ensure_schema(self._pool, schema=self._schema, dimensions=self._dimensions)

    async def put(self, spec_id: str, *, title: str, content: str, project_id: str = "Personal-KB") -> None:
        async with postgres_unavailable():
            await self._pool.execute(
                f"INSERT INTO {self._table} (spec_id, title, content, project_id) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (spec_id) DO UPDATE SET title = EXCLUDED.title, content = EXCLUDED.content, "
                "project_id = EXCLUDED.project_id",
                spec_id,
                title,
                content,
                project_id,
            )

    async def get(self, spec_id: str) -> SpecDocument | None:
        async with postgres_unavailable():
            row = await self._pool.fetchrow(
                f"SELECT spec_id, title, content, project_id FROM {self._table} WHERE spec_id = $1", spec_id
            )
        return (
            SpecDocument(row["spec_id"], row["title"], row["content"], row.get("project_id", "Personal-KB"))
            if row
            else None
        )

    async def all(self) -> list[SpecDocument]:
        """Every stored spec, by id (the catalog of list_sdd_specs)."""
        async with postgres_unavailable():
            rows = await self._pool.fetch(
                f"SELECT spec_id, title, content, project_id FROM {self._table} ORDER BY spec_id"
            )
        return [SpecDocument(r["spec_id"], r["title"], r["content"], r.get("project_id", "Personal-KB")) for r in rows]

    async def delete(self, spec_id: str) -> None:
        async with postgres_unavailable():
            await self._pool.execute(f"DELETE FROM {self._table} WHERE spec_id = $1", spec_id)
