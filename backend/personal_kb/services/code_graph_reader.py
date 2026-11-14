"""CodeGraph SQLite Reader Adapter.

Reads CodeGraph SQLite index (.codegraph/codegraph.db) in read-only mode,
providing structured access to symbols, AST nodes, callers, callees,
and transitive blast radius impact analysis without any LLM token overhead.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "CodeEdge",
    "CodeGraphReader",
    "CodeGraphStatus",
    "CodeNode",
    "CodeRelation",
    "ImpactReport",
    "resolve_db_path",
]


@dataclass(frozen=True)
class CodeNode:
    """Represents a code symbol extracted into the knowledge graph."""

    id: str
    kind: str
    name: str
    qualified_name: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int = 0
    docstring: str | None = None
    signature: str | None = None
    return_type: str | None = None
    is_exported: bool = False
    is_async: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> CodeNode:
        return cls(
            id=str(row["id"]),
            kind=str(row["kind"]),
            name=str(row["name"]),
            qualified_name=str(row["qualified_name"]),
            file_path=str(row["file_path"]),
            language=str(row["language"]),
            start_line=int(row["start_line"]),
            end_line=int(row["end_line"]),
            start_column=int(row["start_column"] or 0),
            end_column=int(row["end_column"] or 0),
            docstring=str(row["docstring"]) if row["docstring"] is not None else None,
            signature=str(row["signature"]) if row["signature"] is not None else None,
            return_type=str(row["return_type"]) if "return_type" in row.keys() and row["return_type"] else None,
            is_exported=bool(row["is_exported"]) if "is_exported" in row.keys() and row["is_exported"] else False,
            is_async=bool(row["is_async"]) if "is_async" in row.keys() and row["is_async"] else False,
        )


@dataclass(frozen=True)
class CodeEdge:
    """Represents a relationship edge between two code nodes."""

    source: str
    target: str
    kind: str
    line: int | None = None
    col: int | None = None
    provenance: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> CodeEdge:
        return cls(
            source=str(row["source"]),
            target=str(row["target"]),
            kind=str(row["kind"]),
            line=int(row["line"]) if row["line"] is not None else None,
            col=int(row["col"]) if "col" in row.keys() and row["col"] is not None else None,
            provenance=str(row["provenance"]) if "provenance" in row.keys() and row["provenance"] else None,
        )


@dataclass(frozen=True)
class CodeRelation:
    """A pair of a related CodeNode and the connecting CodeEdge."""

    node: CodeNode
    edge: CodeEdge


@dataclass(frozen=True)
class ImpactReport:
    """Transitive impact report for a symbol change."""

    symbol: str
    focal_nodes: list[CodeNode]
    impacted_nodes: list[CodeNode]
    edges: list[CodeEdge]
    by_file: dict[str, list[CodeNode]]


@dataclass
class CodeGraphStatus:
    """Status metadata for the CodeGraph SQLite database."""

    available: bool
    db_path: str | None = None
    project_root: str | None = None
    file_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    nodes_by_kind: dict[str, int] = field(default_factory=dict)
    files_by_language: dict[str, int] = field(default_factory=dict)
    db_size_bytes: int = 0
    message: str = ""


def resolve_db_path(project_path: str | Path | None = None) -> Path | None:
    """Resolve the path to .codegraph/codegraph.db walking upwards if needed."""
    if project_path is not None:
        p = Path(project_path).expanduser().resolve()
        if p.is_file() and p.name.endswith(".db"):
            return p
        if p.is_dir():
            candidate = p / ".codegraph" / "codegraph.db"
            if candidate.is_file():
                return candidate
            for parent in p.parents:
                candidate = parent / ".codegraph" / "codegraph.db"
                if candidate.is_file():
                    return candidate
            return None

    cwd = Path.cwd().resolve()
    for directory in [cwd, *cwd.parents]:
        candidate = directory / ".codegraph" / "codegraph.db"
        if candidate.is_file():
            return candidate
    return None


class CodeGraphReader:
    """Reads CodeGraph SQLite database in read-only mode."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        resolved = resolve_db_path(db_path)
        self.db_path = resolved
        self.project_root = resolved.parent.parent if resolved else None

    @property
    def is_available(self) -> bool:
        return self.db_path is not None and self.db_path.is_file()

    def _connect(self) -> sqlite3.Connection:
        if not self.is_available or self.db_path is None:
            raise FileNotFoundError("CodeGraph database (.codegraph/codegraph.db) is not available.")
        # Open in URI read-only mode
        conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_status(self) -> CodeGraphStatus:
        """Inspect the index status, node count, edge count and language distribution."""
        if not self.is_available or self.db_path is None:
            return CodeGraphStatus(
                available=False,
                message=(
                    "Không tìm thấy chỉ mục .codegraph/codegraph.db. "
                    "Hãy khởi tạo bằng lệnh 'codegraph init' tại thư mục gốc của repository."
                ),
            )

        try:
            with self._connect() as conn:
                # Count nodes
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) AS total FROM nodes")
                node_count = cur.fetchone()["total"]

                # Count edges
                cur.execute("SELECT COUNT(*) AS total FROM edges")
                edge_count = cur.fetchone()["total"]

                # Count files
                try:
                    cur.execute("SELECT COUNT(*) AS total FROM files")
                    file_count = cur.fetchone()["total"]
                except sqlite3.OperationalError:
                    cur.execute("SELECT COUNT(DISTINCT file_path) AS total FROM nodes")
                    file_count = cur.fetchone()["total"]

                # Nodes by kind
                cur.execute("SELECT kind, COUNT(*) AS cnt FROM nodes GROUP BY kind ORDER BY cnt DESC")
                nodes_by_kind = {row["kind"]: row["cnt"] for row in cur.fetchall()}

                # Files by language
                try:
                    cur.execute("SELECT language, COUNT(*) AS cnt FROM files GROUP BY language ORDER BY cnt DESC")
                    files_by_lang = {row["language"]: row["cnt"] for row in cur.fetchall()}
                except sqlite3.OperationalError:
                    cur.execute("SELECT language, COUNT(DISTINCT file_path) AS cnt FROM nodes GROUP BY language")
                    files_by_lang = {row["language"]: row["cnt"] for row in cur.fetchall()}

                size_bytes = self.db_path.stat().st_size
                return CodeGraphStatus(
                    available=True,
                    db_path=str(self.db_path),
                    project_root=str(self.project_root),
                    file_count=file_count,
                    node_count=node_count,
                    edge_count=edge_count,
                    nodes_by_kind=nodes_by_kind,
                    files_by_language=files_by_lang,
                    db_size_bytes=size_bytes,
                    message="CodeGraph index is ready.",
                )
        except Exception as e:
            log.warning("Failed to inspect codegraph status: %s", e)
            return CodeGraphStatus(
                available=False,
                db_path=str(self.db_path),
                message=f"Lỗi khi đọc .codegraph/codegraph.db: {e}",
            )

    def search_symbols(
        self,
        query: str,
        kind: str | None = None,
        language: str | None = None,
        limit: int = 15,
    ) -> list[CodeNode]:
        """Search code symbols using FTS5 full-text search with fallback to substring matching."""
        if not self.is_available:
            return []

        limit = max(1, min(limit, 100))
        if kind == "type":
            kind = "type_alias"

        q_clean = query.strip()
        if not q_clean:
            return []

        results: list[CodeNode] = []
        try:
            with self._connect() as conn:
                cur = conn.cursor()

                # Clean tokens for FTS5
                tokens = [re.sub(r"[^a-zA-Z0-9_]", "", t) for t in q_clean.replace("::", " ").split()]
                tokens = [t for t in tokens if t and t.upper() not in {"AND", "OR", "NOT", "NEAR"}]

                fts_success = False
                if tokens:
                    match_expr = " OR ".join(f'"{t}"*' for t in tokens)
                    sql = (
                        "SELECT n.* FROM nodes_fts "
                        "JOIN nodes n ON nodes_fts.id = n.id "
                        "WHERE nodes_fts MATCH ? "
                    )
                    params: list[Any] = [match_expr]
                    if kind:
                        sql += " AND n.kind = ?"
                        params.append(kind)
                    if language:
                        sql += " AND n.language = ?"
                        params.append(language)
                    sql += " ORDER BY bm25(nodes_fts, 0, 20, 5, 1, 2) LIMIT ?"
                    params.append(limit)

                    try:
                        cur.execute(sql, params)
                        rows = cur.fetchall()
                        if rows:
                            results = [CodeNode.from_row(r) for r in rows]
                            fts_success = True
                    except sqlite3.OperationalError:
                        fts_success = False

                if not fts_success or not results:
                    # Fallback to LIKE matching
                    sql = (
                        "SELECT n.* FROM nodes n WHERE "
                        "(n.name LIKE ? OR n.qualified_name LIKE ? OR n.signature LIKE ?) "
                    )
                    like_pat = f"%{q_clean}%"
                    params = [like_pat, like_pat, like_pat]
                    if kind:
                        sql += " AND n.kind = ?"
                        params.append(kind)
                    if language:
                        sql += " AND n.language = ?"
                        params.append(language)
                    sql += " ORDER BY LENGTH(n.name) ASC, n.is_exported DESC LIMIT ?"
                    params.append(limit)

                    cur.execute(sql, params)
                    results = [CodeNode.from_row(r) for r in cur.fetchall()]

        except Exception as e:
            log.warning("CodeGraph symbol search failed: %s", e)
            return []

        return results

    def get_node(self, symbol_or_id: str, file_path: str | None = None) -> CodeNode | None:
        """Find a single focal node by ID, qualified name, or symbol name."""
        if not self.is_available:
            return None

        sym = symbol_or_id.strip()
        if not sym:
            return None

        try:
            with self._connect() as conn:
                cur = conn.cursor()
                # 1. Exact ID match
                cur.execute("SELECT * FROM nodes WHERE id = ? LIMIT 1", (sym,))
                row = cur.fetchone()
                if row:
                    return CodeNode.from_row(row)

                # 2. Exact qualified_name match
                cur.execute("SELECT * FROM nodes WHERE qualified_name = ? LIMIT 1", (sym,))
                row = cur.fetchone()
                if row:
                    return CodeNode.from_row(row)

                # 3. Match by name
                if file_path:
                    clean_file = file_path.strip().lstrip("./")
                    cur.execute(
                        "SELECT * FROM nodes WHERE name = ? AND (file_path = ? OR file_path LIKE ?) "
                        "ORDER BY is_exported DESC, (end_line - start_line) DESC LIMIT 1",
                        (sym, clean_file, f"%/{clean_file}"),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM nodes WHERE name = ? "
                        "ORDER BY is_exported DESC, (end_line - start_line) DESC LIMIT 1",
                        (sym,),
                    )
                row = cur.fetchone()
                if row:
                    return CodeNode.from_row(row)

                # 4. Fallback: suffix match on qualified name
                cur.execute(
                    "SELECT * FROM nodes WHERE qualified_name LIKE ? "
                    "ORDER BY is_exported DESC, (end_line - start_line) DESC LIMIT 1",
                    (f"%::{sym}",),
                )
                row = cur.fetchone()
                if row:
                    return CodeNode.from_row(row)

        except Exception as e:
            log.warning("Failed to get node for %r: %s", symbol_or_id, e)

        return None

    def get_callers(
        self,
        symbol_or_id: str,
        file_path: str | None = None,
        limit: int = 20,
    ) -> list[CodeRelation]:
        """Find functions/methods that call or reference this symbol (incoming relations)."""
        node = self.get_node(symbol_or_id, file_path)
        if not node:
            return []

        limit = max(1, min(limit, 100))
        results: list[CodeRelation] = []

        try:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT e.source, e.target, e.kind AS edge_kind, e.line AS edge_line,
                           e.col AS edge_col, e.provenance, n.*
                    FROM edges e
                    JOIN nodes n ON n.id = e.source
                    WHERE e.target = ? AND e.kind IN ('calls', 'references', 'imports', 'instantiates')
                    ORDER BY n.file_path, n.start_line
                    LIMIT ?
                    """,
                    (node.id, limit),
                )
                for row in cur.fetchall():
                    edge = CodeEdge(
                        source=str(row["source"]),
                        target=str(row["target"]),
                        kind=str(row["edge_kind"]),
                        line=int(row["edge_line"]) if row["edge_line"] is not None else None,
                        col=int(row["edge_col"]) if row["edge_col"] is not None else None,
                        provenance=str(row["provenance"]) if row["provenance"] else None,
                    )
                    caller_node = CodeNode.from_row(row)
                    results.append(CodeRelation(node=caller_node, edge=edge))
        except Exception as e:
            log.warning("Failed to get callers for %s: %s", node.id, e)

        return results

    def get_callees(
        self,
        symbol_or_id: str,
        file_path: str | None = None,
        limit: int = 20,
    ) -> list[CodeRelation]:
        """Find functions/methods called or referenced by this symbol (outgoing relations)."""
        node = self.get_node(symbol_or_id, file_path)
        if not node:
            return []

        limit = max(1, min(limit, 100))
        results: list[CodeRelation] = []

        try:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT e.source, e.target, e.kind AS edge_kind, e.line AS edge_line,
                           e.col AS edge_col, e.provenance, n.*
                    FROM edges e
                    JOIN nodes n ON n.id = e.target
                    WHERE e.source = ? AND e.kind IN ('calls', 'references', 'imports', 'instantiates')
                    ORDER BY n.file_path, n.start_line
                    LIMIT ?
                    """,
                    (node.id, limit),
                )
                for row in cur.fetchall():
                    edge = CodeEdge(
                        source=str(row["source"]),
                        target=str(row["target"]),
                        kind=str(row["edge_kind"]),
                        line=int(row["edge_line"]) if row["edge_line"] is not None else None,
                        col=int(row["edge_col"]) if row["edge_col"] is not None else None,
                        provenance=str(row["provenance"]) if row["provenance"] else None,
                    )
                    callee_node = CodeNode.from_row(row)
                    results.append(CodeRelation(node=callee_node, edge=edge))
        except Exception as e:
            log.warning("Failed to get callees for %s: %s", node.id, e)

        return results

    def get_impact(
        self,
        symbol_or_id: str,
        file_path: str | None = None,
        max_depth: int = 2,
    ) -> ImpactReport:
        """Perform transitive backward BFS along incoming edges (layer-by-batch) to find blast radius."""
        focal_node = self.get_node(symbol_or_id, file_path)
        if not focal_node:
            return ImpactReport(
                symbol=symbol_or_id,
                focal_nodes=[],
                impacted_nodes=[],
                edges=[],
                by_file={},
            )

        max_depth = max(1, min(max_depth, 5))
        visited_ids: set[str] = {focal_node.id}
        impacted_nodes: list[CodeNode] = []
        collected_edges: list[CodeEdge] = []

        container_kinds = {"class", "interface", "struct", "trait", "protocol", "module", "enum"}

        try:
            with self._connect() as conn:
                cur = conn.cursor()
                frontier: set[str] = {focal_node.id}

                # If container, expand contained children into initial frontier
                if focal_node.kind.lower() in container_kinds:
                    cur.execute(
                        "SELECT target FROM edges WHERE source = ? AND kind = 'contains'",
                        (focal_node.id,),
                    )
                    for child_row in cur.fetchall():
                        child_id = str(child_row["target"])
                        frontier.add(child_id)
                        visited_ids.add(child_id)

                for _depth in range(max_depth):
                    if not frontier:
                        break

                    placeholders = ",".join("?" for _ in frontier)
                    cur.execute(
                        f"""
                        SELECT e.source, e.target, e.kind AS edge_kind, e.line AS edge_line,
                               e.col AS edge_col, e.provenance, n.*
                        FROM edges e
                        JOIN nodes n ON n.id = e.source
                        WHERE e.target IN ({placeholders}) AND e.kind != 'contains'
                        ORDER BY n.file_path, n.start_line
                        """,
                        list(frontier),
                    )

                    next_frontier: set[str] = set()
                    for row in cur.fetchall():
                        edge = CodeEdge(
                            source=str(row["source"]),
                            target=str(row["target"]),
                            kind=str(row["edge_kind"]),
                            line=int(row["edge_line"]) if row["edge_line"] is not None else None,
                            col=int(row["edge_col"]) if row["edge_col"] is not None else None,
                            provenance=str(row["provenance"]) if row["provenance"] else None,
                        )
                        collected_edges.append(edge)

                        caller_node = CodeNode.from_row(row)
                        if caller_node.id not in visited_ids:
                            visited_ids.add(caller_node.id)
                            impacted_nodes.append(caller_node)
                            next_frontier.add(caller_node.id)

                    frontier = next_frontier

        except Exception as e:
            log.warning("Impact traversal failed for %s: %s", focal_node.id, e)

        # Group by file_path
        by_file: dict[str, list[CodeNode]] = {}
        for n in impacted_nodes:
            by_file.setdefault(n.file_path, []).append(n)

        return ImpactReport(
            symbol=symbol_or_id,
            focal_nodes=[focal_node],
            impacted_nodes=impacted_nodes,
            edges=collected_edges,
            by_file=by_file,
        )

    def read_code_snippet(self, node: CodeNode) -> str | None:
        """Extract source code slice corresponding to node start_line and end_line with line numbers."""
        if not self.project_root:
            return None

        root_resolved = self.project_root.resolve()
        target_file = (root_resolved / node.file_path).resolve()
        if not target_file.is_relative_to(root_resolved) or not target_file.is_file():
            return None

        try:
            with open(target_file, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            start = max(0, node.start_line - 1)
            end = min(len(lines), node.end_line)
            numbered_lines = [
                f"{line_no}\t{line}"
                for line_no, line in enumerate(lines[start:end], start=start + 1)
            ]
            return "".join(numbered_lines)
        except Exception as e:
            log.debug("Failed to read code snippet for %s: %s", node.file_path, e)
            return None
