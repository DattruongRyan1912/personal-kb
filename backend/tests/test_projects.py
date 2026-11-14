"""project_of: the one rule naming a spec's project (it was copied, with differences, in five modules)."""

from pathlib import Path

import pytest

from personal_kb.services.projects import project_of

KB = Path("/app/knowledge")


def test_the_frontmatter_wins():
    assert project_of("HR-M01", {"project": "CyberOS"}, KB / "Demo-Core" / "HR-M01.md") == "CyberOS"
    assert project_of("X", {"project_id": "MyNotch"}) == "MyNotch"


def test_a_project_folder_under_knowledge_names_it_at_any_depth():
    assert project_of("HR-EX-009", {}, KB / "Demo-Core" / "exemplars" / "HR-EX-009.md") == "Demo-Core"


@pytest.mark.parametrize("folder", ["adrs", "workspaces", "proposals", "docs", "archive"])
def test_a_folder_that_is_not_a_project_falls_back_to_the_prefix(folder):
    assert project_of("MYNOTCH-09", {}, KB / folder / "MYNOTCH-09.md") == "MyNotch"


@pytest.mark.parametrize(
    ("spec_id", "project"),
    [
        ("HR-M09", "Demo-Core"),
        ("hrm-x", "Demo-Core"),
        ("MYNOTCH-02", "MyNotch"),
        ("CYBEROS-04", "CyberOS"),
        ("SDD-AUTH-001", "Personal-KB"),
        ("AGY-02", "AGY-Remote-Hub"),
        ("PKB-07", "Personal-KB"),
        ("KB-01", "Personal-KB"),
    ],
)
def test_the_spec_id_prefix_names_the_project(spec_id, project):
    assert project_of(spec_id, {}, KB / f"{spec_id}.md") == project
    assert project_of(spec_id) == project
