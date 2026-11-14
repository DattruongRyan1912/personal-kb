"""knowledge_files: how a spec file is named, found and created (one rule for the Data Hub and proposals)."""

import pytest

from personal_kb.services.knowledge_files import (
    InvalidSpecPath,
    find_spec_file,
    knowledge_dir,
    new_spec_path,
    spec_files,
    spec_id_of,
    title_of,
)


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / "knowledge"
    (root / "Demo-Core").mkdir(parents=True)
    (root / "proposals").mkdir()
    (root / "KB-01-huong-dan.md").write_text("---\nid: KB-01\ntitle: Hướng dẫn\n---\n# H\n")
    (root / "Demo-Core" / "HR-A.md").write_text("# A\n")
    (root / "proposals" / "HR-A.md").write_text("not a spec\n")
    (root / ".hidden.md").write_text("# hidden\n")
    return root


def test_the_spec_id_is_the_frontmatter_id_or_the_file_name(kb):
    assert spec_id_of(kb / "KB-01-huong-dan.md") == "KB-01"
    assert spec_id_of(kb / "Demo-Core" / "HR-A.md") == "HR-A"


def test_spec_files_skip_proposals_and_hidden_files(kb):
    assert [p.name for p in spec_files(kb)] == ["HR-A.md", "KB-01-huong-dan.md"]


def test_a_spec_is_found_by_its_id_even_when_the_file_is_named_otherwise(kb):
    assert find_spec_file(kb, "KB-01") == (kb / "KB-01-huong-dan.md").resolve()
    assert find_spec_file(kb, "HR-A") == (kb / "Demo-Core" / "HR-A.md").resolve()
    assert find_spec_file(kb, "NOPE") is None


def test_a_new_spec_goes_to_its_project_folder_and_never_outside_knowledge(kb):
    assert new_spec_path(kb, "HR-B", "Demo-Core") == (kb / "Demo-Core" / "HR-B.md").resolve()
    assert new_spec_path(kb, "PKB-9", "Personal-KB") == (kb / "PKB-9.md").resolve()
    with pytest.raises(InvalidSpecPath):
        new_spec_path(kb, "X", "..")
    with pytest.raises(InvalidSpecPath):
        new_spec_path(kb, "", "Personal-KB")


def test_the_title_comes_from_the_frontmatter_then_the_first_heading():
    assert title_of('---\ntitle: "Nghỉ phép"\n---\n# H\n', default="X") == "Nghỉ phép"
    assert title_of("# Tiêu đề\n", default="X") == "Tiêu đề"
    assert title_of("text\n", default="X") == "X"


def test_knowledge_is_found_next_to_or_above_the_working_directory_only(tmp_path, monkeypatch):
    # it once fell back to an absolute path into the CyberOS repo
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "backend").mkdir()
    monkeypatch.chdir(tmp_path / "backend")

    assert knowledge_dir() == (tmp_path / "knowledge").resolve()


def test_the_frontmatter_id_wins_over_a_file_name_that_says_otherwise(kb):
    # X.md declaring id Y must not be taken for spec X when Z.md declares id X: deleting X would unlink the wrong file
    (kb / "X.md").write_text("---\nid: Y\n---\n# Y\n")
    (kb / "Z.md").write_text("---\nid: X\n---\n# X\n")

    assert find_spec_file(kb, "X") == (kb / "Z.md").resolve()
    assert find_spec_file(kb, "Y") == (kb / "X.md").resolve()
