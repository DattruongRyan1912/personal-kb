import json
from pathlib import Path

import pytest

from personal_kb.services.worklog import (
    NewWorklogEntry,
    WorklogValidationError,
    load_project_names,
    validate_entry,
)

PROJECTS = frozenset({"Demo-Core", "MyNotch"})


def entry(**overrides) -> NewWorklogEntry:
    fields = {"project": "MyNotch", "kind": "progress", "summary": "done"} | overrides
    return NewWorklogEntry(**fields)


def test_load_project_names_reads_keys(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"A": {}, "B": {}}))
    assert load_project_names(path) == frozenset({"A", "B"})


def test_load_project_names_missing_file_is_empty(tmp_path):
    assert load_project_names(tmp_path / "nope.json") == frozenset()


def test_the_repo_map_lists_the_five_projects():
    path = Path(__file__).resolve().parents[2] / "config" / "projects.json"
    data = json.loads(path.read_text())
    assert set(data) == {"Demo-Core", "CyberOS", "MyNotch", "AGY-Remote-Hub", "Personal-KB", "Toeic-Study", "Tu_hoc_Toeic"}
    assert all(p["git_author"] == "dattruong19122003@gmail.com" for p in data.values())
    assert load_project_names(path) == frozenset(data)


def test_validate_rejects_unknown_project():
    with pytest.raises(WorklogValidationError, match="project"):
        validate_entry(entry(project="Nope"), PROJECTS)


def test_validate_says_the_project_map_was_not_loaded_when_it_is_empty():
    # a stale bind mount leaves /app/config empty: the error must point there, not at the project name
    with pytest.raises(WorklogValidationError, match="danh sách dự án trống"):
        validate_entry(entry(), frozenset())


def test_validate_rejects_unknown_kind():
    with pytest.raises(WorklogValidationError, match="kind"):
        validate_entry(entry(kind="rant"), PROJECTS)


def test_validate_rejects_empty_summary():
    with pytest.raises(WorklogValidationError, match="summary"):
        validate_entry(entry(summary="   "), PROJECTS)


def test_validate_rejects_summary_over_2000():
    with pytest.raises(WorklogValidationError, match="summary"):
        validate_entry(entry(summary="x" * 2001), PROJECTS)


def test_validate_rejects_next_steps_over_2000():
    with pytest.raises(WorklogValidationError, match="next_steps"):
        validate_entry(entry(next_steps="x" * 2001), PROJECTS)


def test_validate_strips_whitespace():
    assert validate_entry(entry(summary="  x  "), PROJECTS).summary == "x"


def test_validate_redacts_secrets_in_all_text_fields():
    out = validate_entry(
        entry(
            summary="used sk-abcdefghijklmnopqrstuvwxyz123456 here",
            next_steps="POSTGRES_URL=postgresql://u:fakepw123@h/db",
            agent="a",
            branch="feat/x",
        ),
        PROJECTS,
    )
    assert "sk-abc" not in out.summary and "REDACTED" in out.summary
    assert "fakepw123" not in out.next_steps


@pytest.mark.parametrize("field", ["agent", "session_id", "branch"])
def test_metadata_fields_capped_at_200(field):
    validate_entry(entry(**{field: "x" * 200}), PROJECTS)
    with pytest.raises(WorklogValidationError, match=field):
        validate_entry(entry(**{field: "x" * 201}), PROJECTS)


def test_redaction_patterns_match_host_script():
    import importlib.util

    from personal_kb.services.redaction import REDACTIONS

    script = Path(__file__).resolve().parents[2] / "scripts/project_brief.py"
    spec = importlib.util.spec_from_file_location("project_brief_sync", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    norm = lambda items: [(p.pattern, p.flags, r) for p, r in items]  # noqa: E731
    assert norm(REDACTIONS) == norm(mod._REDACTIONS)


def test_validate_checks_the_length_of_the_text_as_written():
    # "[REDACTED]" is longer than the secret it hides: a summary at the limit must not grow past it
    summary = "password=x " + "a" * (2000 - len("password=x "))
    assert len(summary) == 2000

    out = validate_entry(entry(summary=summary), PROJECTS)

    assert "password=[REDACTED]" in out.summary
