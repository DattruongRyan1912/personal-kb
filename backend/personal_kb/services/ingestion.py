"""Ingest SDD Markdown documents into the vector memory (issue 1.2), keeping their history (PoC-A, PoC-A2 #297).

Every chunk is keyed by its headings and content (services/provenance.py). Re-ingesting a document embeds only the
chunks the store does not hold yet; the store then writes them and closes the chunks the document no longer has, one
revision per document. Embedding comes first, so a failed embedding writes and closes nothing.
"""

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from personal_kb.services.chunking import SpecChunk, chunk_markdown, parse_frontmatter
from personal_kb.services.memory_ports import DocumentStore, EmbeddedChunk, VectorStore
from personal_kb.services.projects import project_of
from personal_kb.services.provenance import SourceRevision, keyed_chunks, plan_revision, source_revision

BATCH_SIZE = 100
CONCURRENCY = 4


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class IngestReport:
    documents: int
    chunks: int  # chunks of the documents as they are now
    added: int = 0  # embedded and written by this run
    closed: int = 0  # no longer in their document: valid_to set by this run


def load_source(path: Path) -> tuple[SourceRevision, list[SpecChunk]]:
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    spec_id = str(meta.get("id") or path.stem)
    # the status the spec declares (APPROVED, DRAFT…); a spec without one keeps the schema's default
    status = str(meta.get("status") or SpecChunk.model_fields["status"].default)
    project_id = project_of(spec_id, meta, path)
    return source_revision(spec_id, text, meta), chunk_markdown(
        body, spec_id=spec_id, status=status, project_id=project_id
    )


def load_chunks(path: Path) -> list[SpecChunk]:
    return load_source(path)[1]


def embedding_text(chunk: SpecChunk) -> str:
    """Headings first, so a chunk is found by the topic of its section as well as by its own words."""
    return "\n".join([*chunk.headings, chunk.content])


async def ingest_documents(
    paths: Sequence[Path],
    *,
    embedder: Embedder,
    vectors: VectorStore,
    documents: DocumentStore | None = None,
    observed_at: datetime | None = None,
) -> IngestReport:
    """Chunks to `vectors`; with `documents`, each whole file too, for get_full_spec_content (issue 2.2)."""
    now = observed_at or datetime.now(UTC)
    sources: dict[str, tuple[SourceRevision, list[SpecChunk], Path]] = {}
    for path in paths:
        source, chunks = load_source(path)
        if source.source_id in sources:
            raise ValueError(f"spec id {source.source_id} appears in more than one document ({path})")
        sources[source.source_id] = (source, chunks, path)

    removed: dict[str, set[str]] = {}
    to_embed: list[tuple[str, str, SpecChunk]] = []
    for source, chunks, _ in sources.values():
        plan = plan_revision(await vectors.known_chunk_keys(source.source_id), keyed_chunks(chunks))
        removed[source.source_id] = plan.removed
        to_embed += [(source.source_id, key, chunk) for key, chunk in plan.added]

    limit = asyncio.Semaphore(CONCURRENCY)

    async def embed(batch: list[tuple[str, str, SpecChunk]]) -> list[tuple[str, EmbeddedChunk]]:
        async with limit:
            vectors_ = await embedder.embed([embedding_text(chunk) for _, _, chunk in batch])
        return [
            (spec_id, EmbeddedChunk(key, chunk, vector))
            for (spec_id, key, chunk), vector in zip(batch, vectors_, strict=True)
        ]

    try:
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(embed(to_embed[i : i + BATCH_SIZE])) for i in range(0, len(to_embed), BATCH_SIZE)
            ]
    except ExceptionGroup as failures:
        raise failures.exceptions[0] from None
    embedded: dict[str, list[EmbeddedChunk]] = defaultdict(list)
    for task in tasks:
        for spec_id, chunk in task.result():
            embedded[spec_id].append(chunk)

    added = closed = 0
    for source, _, _ in sources.values():
        result = await vectors.apply_revision(
            source, added=embedded[source.source_id], removed=removed[source.source_id], observed_at=now
        )
        added, closed = added + result.added, closed + result.closed
    for source, chunks, _ in sources.values():
        if chunks:
            # the project comes from the file's place, not its text: a moved spec's unchanged chunks follow it
            await vectors.set_project(source.source_id, chunks[0].project_id)
    if documents is not None:
        for source, chunks, path in sources.values():
            text = path.read_text(encoding="utf-8")
            title = str(parse_frontmatter(text)[0].get("title") or source.source_id)
            project_id = chunks[0].project_id if chunks else "Personal-KB"
            await documents.put(source.source_id, title=title, content=text, project_id=project_id)
    return IngestReport(
        documents=len(sources),
        chunks=sum(len(chunks) for _, chunks, _ in sources.values()),
        added=added,
        closed=closed,
    )
