from personal_kb.services.chunking import MAX_TOKENS, chunk_markdown, count_tokens, parse_frontmatter

CODE = """```python
# a comment, not a heading
def total(items):

    return sum(i.price for i in items)
```"""

TABLE_20_ROWS = "| # | Column | Type |\n|---|---|---|\n" + "\n".join(f"| {i} | col_{i} | text |" for i in range(20))


def prose(words: int) -> str:
    return " ".join(f"word{i % 50}" for i in range(words))


def test_frontmatter_gives_the_spec_id_and_is_removed_from_the_body():
    meta, body = parse_frontmatter("---\nid: SDD-AUTH-001\ntitle: Login\n---\n# 1. Overview\nText.\n")

    assert meta == {"id": "SDD-AUTH-001", "title": "Login"}
    assert body == "# 1. Overview\nText.\n"


def test_frontmatter_with_windows_line_endings_is_read():
    meta, body = parse_frontmatter("---\r\nid: SPC-7\r\nstatus: DRAFT\r\n---\r\n# 1. Overview\r\nText.\r\n")
    assert meta == {"id": "SPC-7", "status": "DRAFT"}
    assert body.startswith("# 1. Overview")


def test_document_without_frontmatter_keeps_its_body():
    assert parse_frontmatter("# Title\nText.") == ({}, "# Title\nText.")


def test_chunk_inherits_every_parent_heading():
    md = "# 1. Overview\nIntro.\n\n## 1.1 Users table\nDetails.\n\n### 1.1.1 Notes\nLast.\n"

    chunks = chunk_markdown(md, spec_id="SDD-1")

    assert [(c.headings, c.content) for c in chunks] == [
        (["# 1. Overview"], "Intro."),
        (["# 1. Overview", "## 1.1 Users table"], "Details."),
        (["# 1. Overview", "## 1.1 Users table", "### 1.1.1 Notes"], "Last."),
    ]


def test_chunk_carries_the_metadata_schema():
    chunk = chunk_markdown("# A\nText.", spec_id="SDD-9")[0]

    assert chunk.model_dump() == {
        "spec_id": "SDD-9",
        "headings": ["# A"],
        "content": "Text.",
        "status": "APPROVED",
        "chunk_index": 0,
        "project_id": "Personal-KB",
    }


def test_text_before_the_first_heading_has_no_headings():
    chunks = chunk_markdown("Preamble.\n\n# A\nText.", spec_id="SDD-1")

    assert chunks[0].headings == []
    assert chunks[0].content == "Preamble."


def test_code_block_is_kept_byte_exact_and_its_comments_are_not_headings():
    md = f"# 1. Flow\nBefore.\n\n{CODE}\n\nAfter.\n"

    chunks = chunk_markdown(md, spec_id="SDD-1")

    assert len(chunks) == 1
    assert chunks[0].headings == ["# 1. Flow"]
    assert chunks[0].content == f"Before.\n\n{CODE}\n\nAfter."


def test_table_in_a_long_section_stays_whole_in_one_chunk():
    md = f"# 1. Data\n{prose(700)}\n\n{TABLE_20_ROWS}\n\n{prose(700)}\n"

    chunks = chunk_markdown(md, spec_id="SDD-1")

    assert len(chunks) > 1
    assert sum(TABLE_20_ROWS in c.content for c in chunks) == 1
    assert all(TABLE_20_ROWS in c.content for c in chunks if "col_" in c.content)  # no chunk holds a fragment


def test_long_prose_is_split_within_the_token_limit_with_overlap():
    md = f"# 1. Long\n{prose(2500)}\n"

    chunks = chunk_markdown(md, spec_id="SDD-1")

    assert len(chunks) >= 3
    assert all(count_tokens(c.content) <= MAX_TOKENS for c in chunks)
    first_tail = chunks[0].content.split()[-10:]
    assert " ".join(first_tail) in chunks[1].content


def test_a_table_larger_than_the_limit_is_never_cut():
    big_table = "| a | b |\n|---|---|\n" + "\n".join(f"| row {i} {prose(20)} | x |" for i in range(60))
    assert count_tokens(big_table) > MAX_TOKENS

    chunks = chunk_markdown(f"# 1. Big\n{big_table}\n", spec_id="SDD-1")

    assert [c.content for c in chunks] == [big_table]


def test_short_section_is_one_chunk_and_indices_follow_document_order():
    md = "# A\nOne.\n\n# B\nTwo.\n\n# C\nThree.\n"

    chunks = chunk_markdown(md, spec_id="SDD-1")

    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert [c.content for c in chunks] == ["One.", "Two.", "Three."]
