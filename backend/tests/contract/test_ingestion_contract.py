"""What ingestion writes besides chunk history (covered by test_vector_store_contract): ids, statuses, documents."""

import pytest

from personal_kb.services.ingestion import ingest_documents
from tests.contract.conftest import FakeEmbedder

ANY = [1.0, 1.0, 0.5, 0.25]


def write(path, spec_id, body="# A\nText.\n", status=None):
    status_line = f"status: {status}\n" if status else ""
    path.write_text(f"---\nid: {spec_id}\n{status_line}---\n{body}")
    return path


async def ingest(paths, vector_store, documents=None):
    return await ingest_documents(paths, embedder=FakeEmbedder(), vectors=vector_store, documents=documents)


async def test_spec_id_falls_back_to_the_file_name(tmp_path, vector_store):
    doc = tmp_path / "SDD-NOID-009.md"
    doc.write_text("# A\nText.\n")

    await ingest([doc], vector_store)

    assert {h.spec_id for h in await vector_store.search(ANY, 10)} == {"SDD-NOID-009"}


async def test_the_status_comes_from_the_frontmatter_and_defaults_to_approved(tmp_path, vector_store, pg_pool):
    await ingest(
        [write(tmp_path / "draft.md", "SPC-8", status="DRAFT"), write(tmp_path / "ok.md", "SPC-9")], vector_store
    )

    rows = await pg_pool.fetch("SELECT spec_id, status FROM chunks WHERE valid_to IS NULL")
    assert {r["spec_id"]: r["status"] for r in rows} == {"SPC-8": "DRAFT", "SPC-9": "APPROVED"}


async def test_two_documents_with_the_same_spec_id_are_refused(tmp_path, vector_store):
    docs = [write(tmp_path / "a.md", "SDD-DUP"), write(tmp_path / "b.md", "SDD-DUP")]

    with pytest.raises(ValueError, match="SDD-DUP"):
        await ingest(docs, vector_store)
    assert await vector_store.search(ANY, 10) == []


async def test_whole_documents_go_to_the_document_store(tmp_path, vector_store, document_store):
    doc = tmp_path / "pay.md"
    doc.write_text("---\nid: SPC-2\ntitle: Luồng thanh toán\n---\n# 1. Tổng quan\nText.\n")

    await ingest([doc], vector_store, documents=document_store)

    stored = await document_store.get("SPC-2")
    assert stored.title == "Luồng thanh toán"
    assert stored.content == doc.read_text()
