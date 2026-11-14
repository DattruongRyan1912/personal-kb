"""Creating the Postgres memory's tables (PoC-A2, #297): schema.sql in one schema, with the embedding size set."""

import re
from pathlib import Path

from personal_kb.core.exceptions import CollectionMismatchError
from personal_kb.infrastructure.postgres.pool import PoolLike, postgres_unavailable

_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")  # the pattern of POSTGRES_SCHEMA: safe to write into SQL unquoted

_EMBEDDING_TYPE = """
SELECT format_type(a.atttypid, a.atttypmod)
FROM pg_attribute a
WHERE a.attrelid = to_regclass($1) AND a.attname = 'embedding' AND NOT a.attisdropped
"""


async def ensure_schema(pool: PoolLike, *, schema: str, dimensions: int) -> bool:
    """Create `schema` and every table of schema.sql in it; True when its `chunks` table did not exist before.

    A `chunks` table of another vector size (a different embedding model) is refused: drop the schema and ingest
    again. Two processes ensuring at once wait for each other.
    """
    if not _NAME.match(schema):
        raise ValueError(f"invalid Postgres schema name {schema!r}")
    async with postgres_unavailable(), pool.acquire() as connection, connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"cyberos-ensure:{schema}")
        existing = await connection.fetchval(_EMBEDDING_TYPE, f"{schema}.chunks")
        if existing is not None and existing != f"vector({dimensions})":
            raise CollectionMismatchError(
                f"{schema}.chunks holds {existing.removeprefix('vector(').removesuffix(')')}-dimensional vectors but "
                f"EMBEDDING_DIMENSIONS is {dimensions}; drop the schema and ingest again"
            )
        await connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        await connection.execute(f"SET LOCAL search_path = {schema}, public")
        await connection.execute(_SCHEMA_SQL.replace("{dimensions}", str(dimensions)))
        # Zero-downtime column migration for pre-existing schemas
        await connection.execute(
            f"ALTER TABLE {schema}.chunks ADD COLUMN IF NOT EXISTS project_id text NOT NULL DEFAULT 'Personal-KB'"
        )
        await connection.execute(f"CREATE INDEX IF NOT EXISTS chunks_project_id ON {schema}.chunks (project_id)")
        await connection.execute(
            f"ALTER TABLE {schema}.documents ADD COLUMN IF NOT EXISTS project_id text NOT NULL DEFAULT 'Personal-KB'"
        )
    return existing is None
