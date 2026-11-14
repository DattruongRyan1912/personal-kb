"""Spec chunks -> LLM graph extraction -> the graph store, one source revision at a time (issue 1.3, PoC-A #297).

Only the chunks the store does not hold yet go to the model; the store closes the facts of chunks the revision no
longer has. A chunk the model answers badly is not recorded, so the next run tries it again; it is never fatal. A
request that fails (after its retries) applies nothing of the revision: otherwise the revision would retract the chunk
an edited chunk replaces before the edited one was read. The other requests are cancelled and the error raised.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from personal_kb.services.chunking import SpecChunk
from personal_kb.services.graph_models import GraphExtraction
from personal_kb.services.memory_ports import GraphStore
from personal_kb.services.provenance import SourceRevision, keyed_chunks, plan_revision

CONCURRENCY = 4


class Extractor(Protocol):
    async def extract(self, chunk: SpecChunk) -> GraphExtraction | None: ...


@dataclass(frozen=True)
class GraphReport:
    chunks: int
    extracted: int
    skipped: int
    kept: int
    removed: int
    opened: int
    closed: int


async def ingest_graph_revision(
    source: SourceRevision,
    chunks: Sequence[SpecChunk],
    *,
    extractor: Extractor,
    store: GraphStore,
    observed_at: datetime | None = None,
) -> GraphReport:
    now = observed_at or datetime.now(UTC)
    plan = plan_revision(await store.known_chunk_keys(source.source_id), keyed_chunks(chunks))
    limit = asyncio.Semaphore(CONCURRENCY)

    async def extract(key: str, chunk: SpecChunk) -> tuple[str, GraphExtraction | None]:
        async with limit:
            return key, await extractor.extract(chunk)

    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(extract(key, chunk)) for key, chunk in plan.added]
    except ExceptionGroup as failures:
        raise failures.exceptions[0] from None
    added = {key: graph for key, graph in (task.result() for task in tasks) if graph is not None}
    result = await store.apply_revision(source, added=added, removed=plan.removed, kept=plan.kept, observed_at=now)
    return GraphReport(
        chunks=len(chunks),
        extracted=len(added),
        skipped=len(plan.added) - len(added),
        kept=len(plan.kept),
        removed=len(plan.removed),
        opened=result.opened,
        closed=result.closed,
    )
