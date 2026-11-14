"""Worklog domain: the append-only progress log that lets one agent pick up where another stopped.

Pure types and validation; the only I/O is reading the project map. Storage sits behind `WorklogStore`.
"""

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

from personal_kb.services.redaction import redact

WORKLOG_KINDS: tuple[str, ...] = ("progress", "decision", "gotcha", "handoff")
MAX_TEXT = 2000
MAX_META = 200


class WorklogValidationError(ValueError):
    """The entry is not acceptable; the message names the field."""


@dataclass(frozen=True)
class NewWorklogEntry:
    project: str
    kind: str
    summary: str
    next_steps: str = ""
    agent: str = ""
    session_id: str = ""
    branch: str = ""


@dataclass(frozen=True, kw_only=True)
class WorklogEntry(NewWorklogEntry):
    id: int
    created_at: datetime


class WorklogStore(Protocol):
    async def ensure(self) -> None: ...

    async def add(self, entry: NewWorklogEntry) -> WorklogEntry: ...

    async def recent(self, project: str = "", *, limit: int = 10, kind: str = "") -> list[WorklogEntry]: ...


def load_project_names(path: Path) -> frozenset[str]:
    """Keys of the project map; a missing or invalid file gives an empty set (every project is then rejected)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    return frozenset(data) if isinstance(data, dict) else frozenset()


def validate_entry(entry: NewWorklogEntry, projects: frozenset[str]) -> NewWorklogEntry:
    """Return the entry with text fields stripped, or raise WorklogValidationError."""
    entry = replace(entry, **{name: getattr(entry, name).strip() for name in _TEXT_FIELDS})
    if not projects:
        raise WorklogValidationError(
            "danh sách dự án trống: backend không đọc được PROJECTS_CONFIG; "
            "kiểm tra mount config/ rồi tạo lại container kb-backend"
        )
    if entry.project not in projects:
        raise WorklogValidationError(f"project không hợp lệ: '{entry.project}' không có trong danh sách dự án")
    if entry.kind not in WORKLOG_KINDS:
        raise WorklogValidationError(f"kind phải là một trong: {', '.join(WORKLOG_KINDS)}")
    if not entry.summary:
        raise WorklogValidationError("summary không được để trống")
    for name in ("summary", "next_steps"):
        if len(getattr(entry, name)) > MAX_TEXT:
            raise WorklogValidationError(f"{name} dài tối đa {MAX_TEXT} ký tự")
    for name in _META_FIELDS:
        if len(getattr(entry, name)) > MAX_META:
            raise WorklogValidationError(f"{name} dài tối đa {MAX_META} ký tự")
    # append-only log: secrets are masked before they can be stored (after the length checks: the mask is longer)
    return replace(entry, **{name: redact(getattr(entry, name)) for name in _REDACTED_FIELDS})


_REDACTED_FIELDS = ("summary", "next_steps", "agent", "session_id", "branch")
_META_FIELDS = ("agent", "session_id", "branch")
_TEXT_FIELDS = ("project", "kind", "summary", "next_steps", "agent", "session_id", "branch")
