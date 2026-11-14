from personal_kb.services.proposals import ProposalStore, apply_to_spec

SPEC = """---
id: SPEC-A
title: t
---

# Spec A

## 1. Build

Steps:

```bash
# build the release
make release
```

Then sign it.

### 1.1 Notes

Old note.

## 2. Hotkeys

Keep this.
"""


def _apply(tmp_path, section: str, content: str) -> str:
    spec = tmp_path / "SPEC-A.md"
    spec.write_text(SPEC, encoding="utf-8")
    prop = ProposalStore(knowledge_dir=tmp_path).create(
        spec_id="SPEC-A", title="t", section=section, proposed_content=content, rationale="r", action="UPDATE_SECTION"
    )
    apply_to_spec(prop, spec)
    return spec.read_text(encoding="utf-8")


def test_a_comment_inside_a_code_block_does_not_end_the_section(tmp_path):
    # "# build the release" was taken for a heading: the update stopped there, the rest of §1 stayed (MYNOTCH-01 §5.2)
    text = _apply(tmp_path, "1. Build", "Run `make release`.")

    assert "make release\n```" not in text and "Then sign it." not in text
    assert "## 1. Build\n\nRun `make release`.\n\n### 1.1 Notes\n\nOld note.\n\n## 2. Hotkeys\n\nKeep this.\n" in text


def test_a_level_three_section_keeps_its_heading(tmp_path):
    text = _apply(tmp_path, "1.1 Notes", "New note.")

    assert "### 1.1 Notes\n\nNew note.\n\n## 2. Hotkeys" in text and "Old note." not in text
    assert "make release" in text


def test_a_heading_inside_a_code_block_is_not_the_section(tmp_path):
    spec_text = SPEC.replace("# build the release", "## 2. Hotkeys")
    spec = tmp_path / "SPEC-A.md"
    spec.write_text(spec_text, encoding="utf-8")
    prop = ProposalStore(knowledge_dir=tmp_path).create(
        spec_id="SPEC-A",
        title="t",
        section="2. Hotkeys",
        proposed_content="New keys.",
        rationale="r",
        action="UPDATE_SECTION",
    )
    apply_to_spec(prop, spec)
    text = spec.read_text(encoding="utf-8")

    assert "```bash\n## 2. Hotkeys\nmake release\n```" in text
    assert text.endswith("## 2. Hotkeys\n\nNew keys.\n") and "Keep this." not in text


def test_a_missing_section_is_appended(tmp_path):
    text = _apply(tmp_path, "3. Logs", "Where logs go.")

    assert text == SPEC.rstrip() + "\n\n## 3. Logs\n\nWhere logs go.\n"
