"""The project a spec belongs to: one rule for ingestion, proposals, the Data Hub, the MCP catalog and anti-collision.

Frontmatter first (`project` or `project_id`), then the project folder directly under knowledge/, then the prefix
of the spec id; anything else is Personal-KB.
"""

from pathlib import Path

DEFAULT_PROJECT = "Personal-KB"

# folders under knowledge/ that group specs without being a project
_NOT_PROJECTS = frozenset({"proposals", "docs", "archive", "adrs", "workspaces", "exemplars"})

_PREFIXES = (
    (("HR-", "HRM-", "HR_"), "Demo-Core"),
    (("MYNOTCH-", "MYNOTCH_"), "MyNotch"),
    # only CYBEROS-*: SDD-*/SPC-* name the sample specs, which ingestion always filed under Personal-KB
    (("CYBEROS",), "CyberOS"),
    (("AGY",), "AGY-Remote-Hub"),
    (("PKB-", "PKB_"), "Personal-KB"),
)


def project_of(spec_id: str, meta: dict | None = None, path: Path | None = None) -> str:
    declared = str((meta or {}).get("project") or (meta or {}).get("project_id") or "").strip()
    if declared:
        return declared
    if path is not None and "knowledge" in path.parts:
        below = path.parts[path.parts.index("knowledge") + 1 : -1]
        if below and below[0] not in _NOT_PROJECTS:
            return below[0]
    stem = spec_id.upper()
    return next((project for prefixes, project in _PREFIXES if stem.startswith(prefixes)), DEFAULT_PROJECT)
