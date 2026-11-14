from datetime import UTC, datetime

import httpx2
import openai
import pytest

from personal_kb.services.graph_models import GraphExtraction, Node
from personal_kb.services.memory_ports import RevisionResult, StaleRevisionError
from scripts.ingest_sdd_to_graph import ingest_paths

AT = datetime(2026, 10, 1, tzinfo=UTC)
REQUEST = httpx2.Request("POST", "http://localhost:11434/v1/chat/completions")


def spec(path, spec_id):
    path.write_text(f"---\nid: {spec_id}\n---\n# 1. A\nText of {spec_id}.\n", encoding="utf-8")
    return path


class FailingFor:
    """A one-node graph per chunk, except for the chunks of `spec_id`, which raise `error`."""

    def __init__(self, spec_id, error):
        self.spec_id, self.error = spec_id, error

    async def extract(self, chunk):
        if chunk.spec_id == self.spec_id:
            raise self.error
        return GraphExtraction(nodes=[Node(id="feature:f", label="Feature")], edges=[])


class Store:
    def __init__(self):
        self.applied = []

    async def known_chunk_keys(self, source_id):
        return set()

    async def apply_revision(self, source, *, added, removed, kept, observed_at):
        self.applied.append(source.source_id)
        return RevisionResult(opened=0, closed=0)


async def test_a_spec_whose_model_call_times_out_is_deferred_and_the_others_are_applied(tmp_path, caplog):
    paths = [spec(tmp_path / "a.md", "SPC-A"), spec(tmp_path / "b.md", "SPC-B"), spec(tmp_path / "c.md", "SPC-C")]
    store = Store()

    deferred = await ingest_paths(
        paths, extractor=FailingFor("SPC-B", openai.APITimeoutError(request=REQUEST)), store=store, now=AT
    )

    assert deferred == ["SPC-B"]
    assert store.applied == ["SPC-A", "SPC-C"]
    assert "SPC-B" in caplog.text and "run again" in caplog.text


async def test_a_model_without_structured_output_stops_the_run(tmp_path):
    error = openai.InternalServerError("not implemented", response=httpx2.Response(501, request=REQUEST), body=None)
    store = Store()

    with pytest.raises(openai.InternalServerError):
        await ingest_paths(
            [spec(tmp_path / "a.md", "SPC-A")], extractor=FailingFor("SPC-A", error), store=store, now=AT
        )
    assert store.applied == []


class StaleFor(Store):
    """Refuses the revision of `spec_id`, as a store does when another run changed its chunk keys meanwhile."""

    def __init__(self, spec_id):
        super().__init__()
        self.spec_id = spec_id

    async def apply_revision(self, source, **kwargs):
        if source.source_id == self.spec_id:
            raise StaleRevisionError(f"{source.source_id}: chunk keys changed since the plan")
        return await super().apply_revision(source, **kwargs)


async def test_a_spec_another_run_changed_meanwhile_is_deferred(tmp_path, caplog):
    paths = [spec(tmp_path / "a.md", "SPC-A"), spec(tmp_path / "b.md", "SPC-B")]
    store = StaleFor("SPC-A")

    deferred = await ingest_paths(paths, extractor=FailingFor("none", RuntimeError()), store=store, now=AT)

    assert deferred == ["SPC-A"]
    assert store.applied == ["SPC-B"]
