"""The vector store contract (PoC-A2): what ingestion and search see, whatever the backend."""

import asyncio
import re
from datetime import timedelta

import pytest

from personal_kb.services.ingestion import ingest_documents
from tests.contract.conftest import T1, T2, T3, DownEmbedder, FakeEmbedder

ANY = [1.0, 1.0, 0.5, 0.25]


def write(path, spec_id, sections: int, changed: dict[int, str] | None = None):
    changed = changed or {}
    body = "\n\n".join(f"# {i}. Section {i}\n{changed.get(i, f'Text of section {i}.')}" for i in range(sections))
    path.write_text(f"---\nid: {spec_id}\n---\n{body}\n")
    return path


async def ingest(paths, store, embedder=None, at=T1):
    return await ingest_documents(paths, embedder=embedder or FakeEmbedder(), vectors=store, observed_at=at)


async def contents(store, as_of=None, spec_id=None) -> list[str]:
    hits = await store.search(ANY, limit=1000, as_of=as_of)
    return sorted(h.content for h in hits if spec_id is None or h.spec_id == spec_id)


async def test_ingesting_unchanged_documents_again_embeds_and_writes_nothing(tmp_path, vector_store):
    docs = [write(tmp_path / "a.md", "SDD-A", 60), write(tmp_path / "b.md", "SDD-B", 40)]
    embedder = FakeEmbedder()
    await ingest(docs, vector_store, embedder)
    batches = list(embedder.batches)

    report = await ingest(docs, vector_store, embedder, at=T2)

    assert (report.added, report.closed) == (0, 0)
    assert embedder.batches == batches
    assert len(await vector_store.known_chunk_keys("SDD-A")) == 60
    assert len(await vector_store.known_chunk_keys("SDD-B")) == 40


async def test_reingesting_a_shorter_document_closes_its_stale_chunks_and_keeps_them(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 5)
    await ingest([doc, write(tmp_path / "b.md", "SDD-B", 2)], vector_store)

    write(doc, "SDD-A", 3)
    report = await ingest([doc], vector_store, at=T2)

    assert (report.added, report.closed) == (0, 2)
    assert len(await contents(vector_store)) == 5  # 3 left of SDD-A, SDD-B untouched
    assert len(await contents(vector_store, as_of=T2 - timedelta(hours=1))) == 7  # the closed 2 stay for the past


async def test_a_changed_section_is_embedded_again_and_its_old_version_closed(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 3)
    await ingest([doc], vector_store)

    write(doc, "SDD-A", 3, changed={1: "New text of section 1."})
    report = await ingest([doc], vector_store, at=T2)

    assert (report.added, report.closed) == (1, 1)
    assert await contents(vector_store) == ["New text of section 1.", "Text of section 0.", "Text of section 2."]
    before = await contents(vector_store, as_of=T2 - timedelta(hours=1))
    assert before == ["Text of section 0.", "Text of section 1.", "Text of section 2."]


async def test_a_section_put_back_later_gets_a_new_point_from_that_time(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 2)
    await ingest([doc], vector_store)
    write(doc, "SDD-A", 1)
    await ingest([doc], vector_store, at=T2)

    write(doc, "SDD-A", 2)
    report = await ingest([doc], vector_store, at=T3)

    assert report.added == 1

    async def section_1(at):
        hits = await vector_store.search(ANY, limit=1000, as_of=at)
        return [h.valid_from for h in hits if h.content == "Text of section 1."]

    assert await section_1(T1 + timedelta(hours=1)) == [T1]
    assert await section_1(T2 + timedelta(hours=1)) == []
    assert await section_1(T3 + timedelta(hours=1)) == [T3]


async def test_the_same_document_saved_with_windows_line_endings_changes_nothing(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 3)
    await ingest([doc], vector_store)

    doc.write_bytes(doc.read_bytes().replace(b"\n", b"\r\n"))
    report = await ingest([doc], vector_store, at=T2)

    assert (report.added, report.closed) == (0, 0)


async def test_a_run_that_fails_while_embedding_is_completed_by_the_next(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 2)
    await ingest([doc], vector_store)
    write(doc, "SDD-A", 2, changed={1: "New text of section 1."})

    with pytest.raises(RuntimeError, match="embedding service down"):
        await ingest([doc], vector_store, DownEmbedder(), at=T2)
    report = await ingest([doc], vector_store, at=T3)

    assert (report.added, report.closed) == (1, 1)
    assert await contents(vector_store) == ["New text of section 1.", "Text of section 0."]


async def test_a_failed_embedding_closes_nothing(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 3)
    await ingest([doc], vector_store)
    keys = await vector_store.known_chunk_keys("SDD-A")
    write(doc, "SDD-A", 3, changed={1: "New text of section 1."})

    with pytest.raises(RuntimeError):
        await ingest([doc], vector_store, DownEmbedder(), at=T2)

    assert await vector_store.known_chunk_keys("SDD-A") == keys
    assert await contents(vector_store) == ["Text of section 0.", "Text of section 1.", "Text of section 2."]


async def test_embeddings_are_requested_in_batches_of_at_most_100(tmp_path, vector_store):
    embedder = FakeEmbedder()

    await ingest([write(tmp_path / "a.md", "SDD-A", 250)], vector_store, embedder)

    assert sorted(embedder.batches, reverse=True) == [100, 100, 50]


async def test_deleting_a_source_removes_all_its_points_past_and_present(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 3)
    await ingest([doc, write(tmp_path / "b.md", "SDD-B", 2)], vector_store)
    write(doc, "SDD-A", 2)
    await ingest([doc], vector_store, at=T2)  # one closed point

    assert await vector_store.delete_source("SDD-A") == 3
    for at in (None, T1 + timedelta(hours=1)):
        hits = await vector_store.search(ANY, limit=1000, as_of=at)
        assert {h.spec_id for h in hits} == {"SDD-B"}
    assert await vector_store.known_chunk_keys("SDD-A") == set()


async def test_deleting_an_unknown_source_removes_nothing(vector_store):
    assert await vector_store.delete_source("SDD-NONE") == 0


async def test_at_the_revision_time_the_new_version_is_valid_and_the_old_is_not(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 2)
    await ingest([doc], vector_store)
    write(doc, "SDD-A", 2, changed={1: "New text of section 1."})
    await ingest([doc], vector_store, at=T2)

    assert await contents(vector_store, as_of=T2) == ["New text of section 1.", "Text of section 0."]
    assert await contents(vector_store, as_of=T2 - timedelta(microseconds=1)) == [
        "Text of section 0.",
        "Text of section 1.",
    ]


async def test_search_hits_are_sorted_by_score_and_carry_their_identity_and_revision(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 4, changed={2: "A much longer text for section two."})
    await ingest([doc], vector_store)

    # FakeEmbedder's vectors differ in direction only by the text length: this one points exactly at section two
    [query] = await FakeEmbedder().embed(["# 2. Section 2\nA much longer text for section two."])
    hits = await vector_store.search(query, limit=3)

    assert len(hits) == 3
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert hits[0].content == "A much longer text for section two."
    assert all(h.spec_id == "SDD-A" and h.valid_from == T1 for h in hits)
    assert all(re.fullmatch(r"[0-9a-f]{16}-0", h.chunk_key) for h in hits)
    assert all(h.revision and h.revision.startswith("sha-") for h in hits)
    assert hits[0].headings == ["# 2. Section 2"]


async def test_two_concurrent_revisions_of_one_source_leave_one_open_row_per_key(tmp_path, vector_store, request):
    doc = write(tmp_path / "a.md", "SDD-A", 5)

    await asyncio.gather(ingest([doc], vector_store), ingest([doc], vector_store, at=T1 + timedelta(seconds=1)))

    hits = await vector_store.search(ANY, limit=1000)
    assert sorted(h.chunk_key for h in hits) == sorted({h.chunk_key for h in hits})
    assert {h.chunk_key for h in hits} == await vector_store.known_chunk_keys("SDD-A")
    assert len(hits) == 5


async def test_a_search_still_fills_its_limit_when_most_chunks_are_closed(tmp_path, vector_store):
    doc = write(tmp_path / "a.md", "SDD-A", 60)
    await ingest([doc], vector_store)
    write(doc, "SDD-A", 10)
    await ingest([doc], vector_store, at=T2)  # closes 50

    assert len(await vector_store.search(ANY, limit=15)) == 10
    assert len(await vector_store.search(ANY, limit=15, as_of=T2 - timedelta(hours=1))) == 15


def write_in(path, spec_id, project: str, body: str):
    path.write_text(f"---\nid: {spec_id}\nproject: {project}\n---\n{body}\n")
    return path


async def test_a_spec_ingested_again_under_another_project_moves_its_unchanged_chunks(tmp_path, vector_store):
    # HR-M01 was first ingested from a copy outside knowledge/Demo-Core: its unchanged chunks kept 'Personal-KB'
    doc = write_in(tmp_path / "a.md", "SDD-A", "Old", "# 1. One\nText one.\n\n# 2. Two\nText two.")
    await ingest([doc], vector_store)

    write_in(doc, "SDD-A", "New", "# 1. One\nText one.\n\n# 2. Two\nText two.")
    report = await ingest([doc], vector_store, at=T2)

    assert report.added == 0
    assert len(await vector_store.search(ANY, limit=10, project_id="New")) == 2
    assert await vector_store.search(ANY, limit=10, project_id="Old") == []


async def test_the_project_filter_ignores_case(tmp_path, vector_store):
    await ingest([write_in(tmp_path / "a.md", "SDD-A", "mynotch", "# 1. One\nText one.")], vector_store)

    assert len(await vector_store.search(ANY, limit=10, project_id="MyNotch")) == 1


async def fts(store, query, project_id=None) -> list[str]:
    return sorted({h.spec_id for h in await store.search_fts(query, 10, project_id=project_id)})


async def test_keyword_search_matches_vietnamese_without_diacritics(tmp_path, postgres_vector_store):
    await ingest(
        [write_in(tmp_path / "a.md", "HR-A", "HRM", "# 1. Lương\nCách tính lương làm thêm giờ.")], postgres_vector_store
    )

    assert await fts(postgres_vector_store, "tinh luong lam them gio") == ["HR-A"]
    assert await fts(postgres_vector_store, "TÍNH LƯƠNG") == ["HR-A"]


async def test_keyword_search_falls_back_to_any_word_when_no_chunk_has_them_all(tmp_path, postgres_vector_store):
    await ingest(
        [
            write_in(tmp_path / "a.md", "HR-A", "HRM", "# 1. OT\nHệ số làm thêm giờ ngày thường là 150%."),
            write_in(tmp_path / "b.md", "HR-B", "HRM", "# 1. Nghỉ\nNghỉ phép năm."),
        ],
        postgres_vector_store,
    )

    # "quy định" and "như thế nào" appear nowhere: an AND of every word would find nothing
    assert await fts(postgres_vector_store, "quy định về hệ số làm thêm giờ như thế nào") == ["HR-A"]


async def test_keyword_search_keeps_requiring_every_word_when_some_chunk_has_them_all(tmp_path, postgres_vector_store):
    await ingest(
        [
            write_in(tmp_path / "a.md", "HR-A", "HRM", "# 1. OT\nHệ số làm thêm giờ."),
            write_in(tmp_path / "b.md", "HR-B", "HRM", "# 1. Giờ\nGiờ làm việc hành chính."),
        ],
        postgres_vector_store,
    )

    assert await fts(postgres_vector_store, "hệ số giờ") == ["HR-A"]


async def test_ensure_rebuilds_a_keyword_index_made_before_accents_were_ignored(
    tmp_path, postgres_vector_store, pg_pool
):
    await ingest([write_in(tmp_path / "a.md", "HR-A", "HRM", "# 1. Lương\nBảng lương.")], postgres_vector_store)
    await pg_pool.execute(
        "ALTER TABLE chunks DROP COLUMN tsv; ALTER TABLE chunks ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (chunks_generate_tsv(headings, content)) STORED"
    )
    assert await fts(postgres_vector_store, "bang luong") == []

    await postgres_vector_store.ensure()

    assert await fts(postgres_vector_store, "bang luong") == ["HR-A"]


async def test_keyword_fallback_ignores_excluded_words(tmp_path, postgres_vector_store):
    await ingest(
        [
            write_in(tmp_path / "a.md", "HR-A", "HRM", "# 1. OT\nHệ số làm thêm giờ."),
            write_in(tmp_path / "b.md", "HR-B", "HRM", "# 1. Nghỉ\nNghỉ phép năm."),
            write_in(tmp_path / "c.md", "HR-C", "HRM", "# 1. Bảo mật\nChính sách bảo mật dữ liệu."),
        ],
        postgres_vector_store,
    )

    # no chunk has "lương": the any-word pass must not turn "-phép" into "or not phép", which matches HR-C
    assert await fts(postgres_vector_store, "hệ số lương -phép") == ["HR-A"]


async def test_keyword_fallback_drops_a_quoted_excluded_phrase(tmp_path, postgres_vector_store):
    await ingest(
        [
            write_in(tmp_path / "a.md", "HR-A", "HRM", "# 1. OT\nHệ số làm thêm giờ."),
            write_in(tmp_path / "b.md", "HR-B", "HRM", "# 1. Nghỉ\nNghỉ phép năm."),
        ],
        postgres_vector_store,
    )

    # -"nghỉ phép" split into -"nghỉ and phép": the fallback searched for the very word excluded
    assert await fts(postgres_vector_store, 'hệ số lương -"nghỉ phép"') == ["HR-A"]


async def test_a_query_of_only_exclusions_finds_nothing(tmp_path, postgres_vector_store):
    await ingest([write_in(tmp_path / "a.md", "HR-A", "HRM", "# 1. OT\nHệ số làm thêm giờ.")], postgres_vector_store)

    # "-phép" alone is "not phép": it matched every chunk without the word
    assert await fts(postgres_vector_store, "-phép") == []


async def test_the_revision_changes_with_every_write_close_move_and_delete(tmp_path, postgres_vector_store):
    # a search is cached under it (HybridRetriever): any change a search could see must change it
    store = postgres_vector_store
    await ingest([write(tmp_path / "b.md", "SDD-B", 2)], store)
    seen = [await store.revision()]
    doc = write_in(tmp_path / "a.md", "SDD-A", "Old", "# 1. One\nText one.\n\n# 2. Two\nText two.")
    await ingest([doc], store)
    seen.append(await store.revision())
    await ingest([doc], store, at=T2)  # nothing changed
    assert await store.revision() == seen[-1]

    write_in(doc, "SDD-A", "Old", "# 1. One\nText one.")
    await ingest([doc], store, at=T2)  # a chunk closed
    seen.append(await store.revision())
    write_in(doc, "SDD-A", "New", "# 1. One\nText one.")
    await ingest([doc], store, at=T3)  # moved to another project, nothing written
    seen.append(await store.revision())
    await store.delete_source("SDD-A")
    seen.append(await store.revision())

    # deleting SDD-A brings back the rows before it, and with them the results a search had then
    assert all(a != b for a, b in zip(seen, seen[1:], strict=False)) and seen[-1] == seen[0]
