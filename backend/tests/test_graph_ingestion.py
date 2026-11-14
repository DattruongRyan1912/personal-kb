import asyncio
from datetime import UTC, datetime

import httpx2
import openai
import pytest

from personal_kb.services.chunking import SpecChunk
from personal_kb.services.graph_ingestion import ingest_graph_revision
from personal_kb.services.graph_models import GraphExtraction, Node
from personal_kb.services.memory_ports import RevisionResult
from personal_kb.services.provenance import SourceRevision, keyed_chunks

AT = datetime(2026, 10, 1, tzinfo=UTC)
SOURCE = SourceRevision("SPC-1", "1", "hash")


def chunk(index: int, text: str | None = None) -> SpecChunk:
    return SpecChunk(spec_id="SPC-1", headings=[], content=text or f"SPC-1 part {index}", chunk_index=index)


class FakeExtractor:
    """A one-node graph per chunk, or None (a skipped chunk) for the contents listed in `invalid`; counts calls."""

    def __init__(self, invalid=()):
        self.invalid, self.seen = set(invalid), []

    async def extract(self, c: SpecChunk):
        self.seen.append(c.content)
        if c.content in self.invalid:
            return None
        return GraphExtraction(nodes=[Node(id=f"feature:f{c.chunk_index}", label="Feature")], edges=[])


class FakeStore:
    """Remembers the chunk keys of each source like the Neo4j store; records every revision applied."""

    def __init__(self):
        self.keys: dict[str, set[str]] = {}
        self.applied = []

    async def known_chunk_keys(self, source_id):
        return set(self.keys.get(source_id, set()))

    async def apply_revision(self, source, *, added, removed, kept, observed_at):
        self.applied.append((source.source_id, sorted(added), sorted(removed), sorted(kept), observed_at))
        self.keys[source.source_id] = kept | set(added)
        return RevisionResult(opened=len(added), closed=len(removed))


async def test_a_first_revision_extracts_every_chunk():
    store, extractor = FakeStore(), FakeExtractor()
    chunks = [chunk(0), chunk(1)]

    report = await ingest_graph_revision(SOURCE, chunks, extractor=extractor, store=store, observed_at=AT)

    keys = sorted(k for k, _ in keyed_chunks(chunks))
    assert store.applied == [("SPC-1", keys, [], [], AT)]
    assert (report.chunks, report.extracted, report.skipped, report.kept, report.removed) == (2, 2, 0, 0, 0)


async def test_an_unchanged_revision_sends_nothing_to_the_model():
    store, extractor = FakeStore(), FakeExtractor()
    chunks = [chunk(0), chunk(1)]
    await ingest_graph_revision(SOURCE, chunks, extractor=extractor, store=store, observed_at=AT)
    extractor.seen.clear()

    report = await ingest_graph_revision(SOURCE, chunks, extractor=extractor, store=store, observed_at=AT)

    assert extractor.seen == []
    assert (report.extracted, report.kept, report.removed) == (0, 2, 0)


async def test_only_a_changed_chunk_is_extracted_and_its_old_key_removed():
    store, extractor = FakeStore(), FakeExtractor()
    await ingest_graph_revision(SOURCE, [chunk(0), chunk(1)], extractor=extractor, store=store, observed_at=AT)
    old_key = keyed_chunks([chunk(1)])[0][0]
    extractor.seen.clear()

    report = await ingest_graph_revision(
        SOURCE, [chunk(0), chunk(1, "SPC-1 part 1, edited")], extractor=extractor, store=store, observed_at=AT
    )

    assert extractor.seen == ["SPC-1 part 1, edited"]
    assert store.applied[-1][2] == [old_key]
    assert (report.extracted, report.kept, report.removed, report.closed) == (1, 1, 1, 1)


async def test_a_skipped_chunk_is_not_recorded_so_the_next_run_tries_it_again():
    store = FakeStore()
    chunks = [chunk(0), chunk(1), chunk(2)]

    first = await ingest_graph_revision(
        SOURCE, chunks, extractor=FakeExtractor(invalid={"SPC-1 part 1"}), store=store, observed_at=AT
    )
    retry = FakeExtractor()
    second = await ingest_graph_revision(SOURCE, chunks, extractor=retry, store=store, observed_at=AT)

    assert (first.extracted, first.skipped) == (2, 1)
    assert retry.seen == ["SPC-1 part 1"]
    assert (second.extracted, second.kept) == (1, 2)


class StalledExtractor:
    """Raises `error` for the chunk whose content is `fails`; every other chunk waits until it is cancelled."""

    def __init__(self, fails: str, error: Exception):
        self.fails, self.error, self.cancelled = fails, error, []

    async def extract(self, c: SpecChunk):
        if c.content == self.fails:
            raise self.error
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.append(c.content)
            raise


async def test_a_failed_request_applies_nothing_and_cancels_the_other_requests():
    # nothing of the revision is written, so it cannot retract chunks whose replacement never arrived; the next run
    # does the whole revision again
    store = FakeStore()
    timeout = openai.APITimeoutError(request=httpx2.Request("POST", "http://localhost:11434/v1/chat/completions"))
    extractor = StalledExtractor("SPC-1 part 0", timeout)

    with pytest.raises(openai.APITimeoutError):
        await ingest_graph_revision(SOURCE, [chunk(0), chunk(1)], extractor=extractor, store=store, observed_at=AT)

    assert store.applied == []
    assert extractor.cancelled == ["SPC-1 part 1"]
