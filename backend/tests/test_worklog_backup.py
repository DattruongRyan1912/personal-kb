from datetime import UTC, datetime

from personal_kb.services.worklog import WorklogEntry
from scripts.worklog_backup import from_line, to_line


def test_a_backup_line_round_trips_every_field():
    e = WorklogEntry(
        id=7,
        project="MyNotch",
        kind="handoff",
        summary="xong bước 2",
        next_steps="bước 3",
        agent="claude",
        session_id="s1",
        branch="main",
        created_at=datetime(2026, 10, 25, 3, 4, 5, 678000, tzinfo=UTC),
    )

    line = to_line(e)

    assert "\n" not in line and '"summary": "xong bước 2"' in line
    assert from_line(line) == e


def test_a_secret_written_before_redaction_existed_is_masked_in_the_backup():
    # entry #5 (2026-10-24) predates redaction on write: the backup goes to git, so it is masked again on export
    e = WorklogEntry(
        id=5,
        project="P",
        kind="progress",
        summary="check OPENAI_API_KEY=sk-abcdefghijklmnopqrstu",
        next_steps="use OPENAI_API_KEY=sk-abcdefghijklmnopqrstu",
        agent="a",
        session_id="",
        branch="",
        created_at=datetime(2026, 10, 24, tzinfo=UTC),
    )

    line = to_line(e)

    assert "sk-abc" not in line and line.count("[REDACTED]") == 2
