"""The asyncpg pool of the Postgres memory backend, and its connection errors as dependency errors (PoC-A2, #297).

The DSN holds the password: no error, log line or traceback built here carries it, only the host and port.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import asyncpg
from pgvector.asyncpg import register_vector

from personal_kb.core.config import Settings
from personal_kb.core.exceptions import DependencyUnavailableError

CONNECT_TIMEOUT_SECONDS = 2  # a search must fail fast when Postgres is down
COMMAND_TIMEOUT_SECONDS = 10
_EXTENSIONS = (
    "CREATE EXTENSION IF NOT EXISTS vector SCHEMA public; CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public"
)
# what connecting can raise: refused or unresolvable host, timeout, bad credentials or database, malformed DSN
_CONNECT_ERRORS = (OSError, TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError)


async def create_pool(settings: Settings, *, schema: str | None = None) -> asyncpg.Pool:
    """A pool whose search_path is `schema` (default POSTGRES_SCHEMA), then public, with the pgvector codec.

    The extensions are created first, on their own connection: the codec of every pooled connection needs the vector
    type, which a fresh database does not have yet.
    """
    if settings.postgres_url is None:
        raise DependencyUnavailableError("postgres", "POSTGRES_URL is not set")
    dsn = settings.postgres_url.get_secret_value()
    try:
        connection = await asyncpg.connect(dsn, timeout=CONNECT_TIMEOUT_SECONDS)
    except _CONNECT_ERRORS as exc:
        raise _cannot_connect(dsn, exc) from None
    try:
        await connection.execute(_EXTENSIONS)
    except asyncpg.PostgresError as exc:  # e.g. a role that may not create extensions
        raise DependencyUnavailableError(
            "postgres", f"cannot create the vector and pg_trgm extensions ({type(exc).__name__})"
        ) from exc
    finally:
        await connection.close()
    try:
        return await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=settings.postgres_pool_size,
            timeout=CONNECT_TIMEOUT_SECONDS,
            command_timeout=COMMAND_TIMEOUT_SECONDS,
            server_settings={"search_path": f"{schema or settings.postgres_schema}, public"},
            init=register_vector,
        )
    except _CONNECT_ERRORS as exc:
        raise _cannot_connect(dsn, exc) from None


class LazyPool:
    """An asyncpg pool created on first use (spec 4.3): the app starts while Postgres is still down, and every call
    until it answers fails fast with DependencyUnavailableError, like any other backing service. A failed connect is
    retried on the next call."""

    def __init__(self, connect: Callable[[], Awaitable[asyncpg.Pool]]) -> None:
        self._connect = connect
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            async with self._lock:
                if self._pool is None:
                    self._pool = await self._connect()
        return self._pool

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        async with (await self.pool()).acquire() as connection:
            yield connection

    async def execute(self, query: str, *args) -> str:
        return await (await self.pool()).execute(query, *args)

    async def fetch(self, query: str, *args) -> list[asyncpg.Record]:
        return await (await self.pool()).fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> asyncpg.Record | None:
        return await (await self.pool()).fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        return await (await self.pool()).fetchval(query, *args)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()


PoolLike = asyncpg.Pool | LazyPool  # what the Postgres stores run their queries on


_UNAVAILABLE = (
    OSError,
    TimeoutError,
    asyncpg.PostgresConnectionError,
    asyncpg.InterfaceError,
    asyncpg.OperatorInterventionError,  # 57: shutting down, cannot connect now, query cancelled
    asyncpg.InsufficientResourcesError,  # 53: too many connections, disk full
    asyncpg.InvalidAuthorizationSpecificationError,  # 28: a password refused on reconnect
)
_NOT_INITIALISED = (asyncpg.UndefinedTableError, asyncpg.InvalidSchemaNameError)


@asynccontextmanager
async def postgres_unavailable() -> AsyncIterator[None]:
    """Postgres down, full or not set up yet, as the 503 every backing service gives (the search's fail-safe paths
    and the tools' "store unavailable" answer depend on it)."""
    try:
        yield
    except _NOT_INITIALISED as exc:
        raise DependencyUnavailableError(
            "postgres",
            f"the memory tables do not exist ({type(exc).__name__}): "
            "run POST /api/v1/system/init-db, then the ingestion",
        ) from exc
    except _UNAVAILABLE as exc:
        raise DependencyUnavailableError("postgres", type(exc).__name__) from exc


def _cannot_connect(dsn: str, exc: BaseException) -> DependencyUnavailableError:
    # `from None` at the raise: asyncpg's own message may repeat the DSN
    return DependencyUnavailableError("postgres", f"cannot connect to {_server(dsn)} ({type(exc).__name__})")


def _server(dsn: str) -> str:
    """host:port of the DSN, unless the DSN is ambiguous: a password with an unencoded '@' or '/' would otherwise be
    split into a "host" that is a piece of the password."""
    try:
        parts = urlsplit(dsn)
        host, port, password = parts.hostname or "localhost", parts.port or 5432, parts.password
    except ValueError:
        return "the configured server"
    if dsn.partition("://")[2].count("@") > 1 or (password and host in password):
        return "the configured server"
    return f"{host}:{port}"
