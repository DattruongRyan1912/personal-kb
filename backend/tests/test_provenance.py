import re

from personal_kb.services.chunking import SpecChunk
from personal_kb.services.provenance import (
    SourceRevision,
    assertion,
    chunk_key,
    keyed_chunks,
    plan_revision,
    source_revision,
)


def chunk(content: str, headings=("# 1. Tổng quan",), index=0) -> SpecChunk:
    return SpecChunk(spec_id="SPC-2", headings=list(headings), content=content, chunk_index=index)


def test_a_chunk_key_depends_on_headings_and_content_only():
    key = chunk_key(chunk("Bảng `payments`."))

    assert re.fullmatch(r"[0-9a-f]{16}", key)
    assert chunk_key(chunk("Bảng `payments`.", index=7)) == key  # moving a chunk keeps its key
    assert chunk_key(chunk("Bảng `payment_transactions`.")) != key
    assert chunk_key(chunk("Bảng `payments`.", headings=("# 2. API",))) != key


def test_identical_chunks_of_one_spec_get_distinct_keys():
    keyed = keyed_chunks([chunk("same"), chunk("other"), chunk("same")])

    keys = [key for key, _ in keyed]
    assert keys[0].endswith("-0") and keys[2].endswith("-1") and keys[1].endswith("-0")
    assert keys[0][:16] == keys[2][:16] and len(set(keys)) == 3


def test_an_assertion_names_the_source_and_the_chunk():
    assert assertion("SPC-2", "abc-0") == "SPC-2#abc-0"


def test_the_revision_is_the_frontmatter_version_or_a_content_hash():
    text = "---\nid: SPC-2\nversion: 2\n---\n# A\n"

    versioned = source_revision("SPC-2", text, {"id": "SPC-2", "version": 2})
    unversioned = source_revision("SPC-2", text, {"id": "SPC-2"})

    assert versioned == SourceRevision("SPC-2", "2", versioned.content_hash)
    assert re.fullmatch(r"[0-9a-f]{64}", versioned.content_hash)
    assert unversioned.revision == f"sha-{versioned.content_hash[:12]}"


def test_a_revision_plan_adds_new_keys_removes_missing_ones_and_keeps_the_rest():
    a, b, c = chunk("a"), chunk("b"), chunk("c")
    keyed = keyed_chunks([a, c])
    key_a, key_c = keyed[0][0], keyed[1][0]
    key_b = keyed_chunks([b])[0][0]

    plan = plan_revision({key_a, key_b}, keyed)

    assert [k for k, _ in plan.added] == [key_c]
    assert plan.removed == {key_b}
    assert plan.kept == {key_a}


def test_a_first_revision_adds_everything():
    keyed = keyed_chunks([chunk("a"), chunk("b")])

    plan = plan_revision(set(), keyed)

    assert [k for k, _ in plan.added] == [k for k, _ in keyed]
    assert plan.removed == set() and plan.kept == set()
