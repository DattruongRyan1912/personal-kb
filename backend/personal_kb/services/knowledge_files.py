"""Spec files in knowledge/: how one is named, found and created. Shared by the Data Hub and the proposal store.

A spec's id is its frontmatter `id`, else its file name (as ingestion reads it): KB-01 lives in KB-01-huong-dan.md.
"""

import re
from collections.abc import Iterator
from pathlib import Path

from personal_kb.services.chunking import parse_frontmatter

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


class InvalidSpecPath(ValueError):
    """A spec id or project folder that is empty or would leave knowledge/."""


def knowledge_dir() -> Path:
    """knowledge/ in the working directory (the container's /app) or its parent (backend/ in the repo)."""
    for candidate in (Path("knowledge"), Path("../knowledge")):
        if candidate.is_dir():
            return candidate.resolve()
    default = Path("knowledge")
    default.mkdir(parents=True, exist_ok=True)
    return default.resolve()


def spec_files(root: Path) -> Iterator[Path]:
    """Every spec under `root`, sorted; proposals, templates and hidden files are not specs."""
    return iter(
        sorted(
            p
            for p in root.rglob("*.md")
            if p.is_file() and not p.name.startswith(".") and "proposals" not in p.parts and "templates" not in p.parts
        )
    )


def spec_id_of(path: Path, text: str | None = None) -> str:
    meta, _ = parse_frontmatter(path.read_text(encoding="utf-8") if text is None else text)
    return str(meta.get("id") or path.stem)


def title_of(text: str, default: str) -> str:
    meta, body = parse_frontmatter(text)
    if meta.get("title"):
        return str(meta["title"]).strip()
    heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    return heading.group(1).strip() if heading else default


def find_spec_file(root: Path, spec_id: str) -> Path | None:
    """The file whose spec id (frontmatter id, else file name) is `spec_id`, as ingestion identifies it."""
    root = root.resolve()
    for path in spec_files(root):
        if spec_id_of(path) == spec_id and path.resolve().is_relative_to(root):
            return path.resolve()
    return None


def new_spec_path(root: Path, spec_id: str, project_id: str) -> Path:
    """Where a new spec is written: knowledge/<project>/<id>.md, or knowledge/<id>.md for Personal-KB."""
    root = root.resolve()
    name, project = _UNSAFE.sub("_", spec_id), _UNSAFE.sub("_", (project_id or "").strip())
    if not name:
        raise InvalidSpecPath("Mã tài liệu không hợp lệ")
    folder = root / project if project and project != "Personal-KB" else root
    path = (folder / f"{name}.md").resolve()
    if not folder.resolve().is_relative_to(root) or not path.is_relative_to(root):
        raise InvalidSpecPath("Đường dẫn không hợp lệ (path traversal)")
    return path
