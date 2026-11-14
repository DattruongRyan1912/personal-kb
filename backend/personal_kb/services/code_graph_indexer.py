"""Native Tree-sitter CodeGraph Indexer & Two-Pass Linker.

Extracts AST symbol nodes, unresolved references, and imports across multiple
programming languages using native tree-sitter grammars (zero LLM token cost).
Resolves symbol references via a two-pass linker and persists into a CodeGraph-compatible
SQLite database with FTS5 search and incremental SHA-256 caching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tree_sitter
    from tree_sitter_language_pack import get_parser
except ImportError:
    tree_sitter = None
    get_parser = None

log = logging.getLogger(__name__)

__all__ = [
    "CodeGraphIndexer",
    "IndexResult",
    "ParsedSymbol",
    "UnresolvedRef",
]

# Supported language extensions mapping to tree-sitter-language-pack identifiers
LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".swift": "swift",
    ".dart": "dart",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}

# Directories and patterns to ignore during file discovery
IGNORE_DIRS: set[str] = {
    ".git",
    ".codegraph",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".build",
    ".dart_tool",
    ".next",
    ".turbo",
    "Pods",
    "DerivedData",
    "target",
    "bin",
    "obj",
}


@dataclass
class ParsedSymbol:
    """A code symbol extracted from an AST."""

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
    visibility: str = "public"
    is_exported: bool = False
    is_async: bool = False
    is_static: bool = False
    is_abstract: bool = False
    decorators: list[str] = field(default_factory=list)
    type_parameters: str | None = None
    return_type: str | None = None
    parent_id: str | None = None


@dataclass
class UnresolvedRef:
    """An unresolved reference (function call, import, instantiation, or reference)."""

    caller_id: str
    target_name: str
    kind: str  # calls, imports, references, instantiates
    file_path: str
    line: int
    col: int
    import_source: str | None = None


@dataclass
class IndexResult:
    """Summary telemetry of an indexation run."""

    project_root: str
    db_path: str
    files_indexed: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    nodes_count: int = 0
    edges_count: int = 0
    db_size_bytes: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": self.project_root,
            "db_path": self.db_path,
            "files_indexed": self.files_indexed,
            "files_skipped": self.files_skipped,
            "files_deleted": self.files_deleted,
            "nodes_count": self.nodes_count,
            "edges_count": self.edges_count,
            "db_size_bytes": self.db_size_bytes,
            "duration_seconds": round(self.duration_seconds, 3),
            "errors": self.errors,
        }


class CodeGraphIndexer:
    """Indexes source code repositories into CodeGraph SQLite databases using tree-sitter."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).expanduser().resolve()
        self.codegraph_dir = self.project_root / ".codegraph"
        self.db_path = self.codegraph_dir / "codegraph.db"
        self._parsers: dict[str, Any] = {}

    def _get_parser(self, language: str) -> Any:
        if language in self._parsers:
            return self._parsers[language]
        if get_parser is None:
            raise RuntimeError("tree-sitter-language-pack is not installed")
        try:
            parser = get_parser(language)
            self._parsers[language] = parser
            return parser
        except Exception as e:
            log.warning("Failed to load parser for %s: %s", language, e)
            return None

    def init_db(self, force: bool = False) -> sqlite3.Connection:
        """Initialize SQLite database with CodeGraph schema and FTS5 triggers."""
        self.codegraph_dir.mkdir(parents=True, exist_ok=True)
        if force and self.db_path.exists():
            try:
                self.db_path.unlink()
                wal = self.db_path.with_name(self.db_path.name + "-wal")
                shm = self.db_path.with_name(self.db_path.name + "-shm")
                if wal.exists():
                    wal.unlink()
                if shm.exists():
                    shm.unlink()
            except Exception as e:
                log.warning("Could not delete old db file: %s", e)

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA foreign_keys = ON;")

        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                qualified_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                language TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                start_column INTEGER DEFAULT 0,
                end_column INTEGER DEFAULT 0,
                docstring TEXT,
                signature TEXT,
                visibility TEXT DEFAULT 'public',
                is_exported INTEGER DEFAULT 0,
                is_async INTEGER DEFAULT 0,
                is_static INTEGER DEFAULT 0,
                is_abstract INTEGER DEFAULT 0,
                decorators TEXT,
                type_parameters TEXT,
                return_type TEXT,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                kind TEXT NOT NULL,
                metadata TEXT,
                line INTEGER,
                col INTEGER,
                provenance TEXT
            );

            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                language TEXT NOT NULL,
                size INTEGER NOT NULL,
                modified_at INTEGER NOT NULL,
                indexed_at INTEGER NOT NULL,
                node_count INTEGER DEFAULT 0,
                errors TEXT
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            -- Compatibility tables for bidirectional interoperability with Volta codegraph CLI
            CREATE TABLE IF NOT EXISTS schema_versions (
                version INTEGER PRIMARY KEY,
                applied_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS unresolved_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                symbol_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                line INTEGER,
                col INTEGER,
                provenance TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
            CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
            CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
            CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
            CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
            """
        )

        # Initialize FTS5 table and sync triggers
        cur.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                id UNINDEXED,
                name,
                qualified_name,
                docstring,
                signature,
                tokenize='unicode61'
            );
            """
        )
        cur.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
                INSERT INTO nodes_fts(id, name, qualified_name, docstring, signature)
                VALUES (new.id, new.name, new.qualified_name, new.docstring, new.signature);
            END;

            CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
                DELETE FROM nodes_fts WHERE id = old.id;
            END;

            CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
                UPDATE nodes_fts SET
                    name = new.name,
                    qualified_name = new.qualified_name,
                    docstring = new.docstring,
                    signature = new.signature
                WHERE id = old.id;
            END;
            """
        )
        conn.commit()
        return conn

    def discover_files(self) -> list[tuple[Path, str, str]]:
        """Walk project directory, filter ignore paths, return (path, rel_path, language)."""
        discovered: list[tuple[Path, str, str]] = []
        for root, dirs, files in os.walk(self.project_root):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
            for file in files:
                if file.startswith("."):
                    continue
                file_path = Path(root) / file
                ext = file_path.suffix.lower()
                if ext in LANGUAGE_MAP:
                    try:
                        rel_path = file_path.relative_to(self.project_root).as_posix()
                        discovered.append((file_path, rel_path, LANGUAGE_MAP[ext]))
                    except ValueError:
                        continue
        return discovered

    def _hash_file(self, path: Path) -> tuple[str, int, int]:
        """Return (sha256_hex, size_bytes, mtime_int)."""
        stat = path.stat()
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest(), stat.st_size, int(stat.st_mtime)

    # -------------------------------------------------------------------------
    # PASS 1: AST Extraction
    # -------------------------------------------------------------------------

    def parse_file(
        self,
        file_path: Path,
        rel_path: str,
        language: str,
    ) -> tuple[list[ParsedSymbol], list[UnresolvedRef], str | None]:
        """Parse source code with tree-sitter into symbols and unresolved references."""
        parser = self._get_parser(language)
        if parser is None:
            return [], [], f"Parser unavailable for {language}"

        try:
            with open(file_path, "rb") as f:
                source_bytes = f.read()
        except Exception as e:
            return [], [], f"Failed to read file: {e}"

        try:
            tree = parser.parse(source_bytes)
        except Exception as e:
            return [], [], f"Parser syntax error: {e}"

        symbols: list[ParsedSymbol] = []
        unresolved: list[UnresolvedRef] = []

        if language == "python":
            self._extract_python(tree.root_node, source_bytes, rel_path, symbols, unresolved)
        elif language in ("typescript", "tsx", "javascript"):
            self._extract_typescript(tree.root_node, source_bytes, rel_path, language, symbols, unresolved)
        elif language == "swift":
            self._extract_swift(tree.root_node, source_bytes, rel_path, symbols, unresolved)
        elif language == "dart":
            self._extract_dart(tree.root_node, source_bytes, rel_path, symbols, unresolved)
        else:
            self._extract_generic(tree.root_node, source_bytes, rel_path, language, symbols, unresolved)

        return symbols, unresolved, None

    def _get_node_text(self, node: Any, source_bytes: bytes) -> str:
        return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _get_point(node: Any) -> tuple[int, int, int, int]:
        """Safely extract (start_line, end_line, start_col, end_col) as pure Python ints."""
        sp = node.start_point
        ep = node.end_point
        return int(sp[0]) + 1, int(ep[0]) + 1, int(sp[1]), int(ep[1])

    def _extract_docstring(self, body_node: Any, source: bytes) -> str | None:
        if not body_node or not body_node.children:
            return None
        first = body_node.children[0]
        if first.type == "string":
            return self._get_node_text(first, source).strip("'\" \n\t")
        if first.type == "expression_statement" and first.children:
            sub = first.children[0]
            if sub.type == "string":
                return self._get_node_text(sub, source).strip("'\" \n\t")
        return None

    def _extract_python(
        self,
        root: Any,
        source: bytes,
        rel_path: str,
        symbols: list[ParsedSymbol],
        unresolved: list[UnresolvedRef],
    ) -> None:
        file_symbol_id = f"{rel_path}#"

        def visit(node: Any, current_scope: list[str], parent_id: str | None) -> None:
            nonlocal file_symbol_id

            # Class definition
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    node_id = f"{rel_path}#{qname}"

                    # Superclasses / instantiations
                    superclasses = node.child_by_field_name("superclasses")
                    if superclasses:
                        for child in superclasses.children:
                            if child.type in ("identifier", "attribute"):
                                sc_name = self._get_node_text(child, source).split(".")[-1]
                                unresolved.append(
                                    UnresolvedRef(
                                        caller_id=node_id,
                                        target_name=sc_name,
                                        kind="references",
                                        file_path=rel_path,
                                        line=int(child.start_point[0]) + 1,
                                        col=int(child.start_point[1]),
                                    )
                                )

                    # Docstring
                    body = node.child_by_field_name("body")
                    docstring = self._extract_docstring(body, source)

                    s_line, e_line, s_col, e_col = self._get_point(node)
                    sym = ParsedSymbol(
                        id=node_id,
                        kind="class",
                        name=name,
                        qualified_name=qname,
                        file_path=rel_path,
                        language="python",
                        start_line=s_line,
                        end_line=e_line,
                        start_column=s_col,
                        end_column=e_col,
                        docstring=docstring,
                        signature=f"class {name}",
                        parent_id=parent_id,
                    )
                    symbols.append(sym)

                    # Recurse inside class body
                    if body:
                        for child in body.children:
                            visit(child, [*current_scope, name], node_id)
                    return

            # Function or Method definition
            elif node.type in ("function_definition", "async_function_definition"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    is_method = bool(current_scope)
                    kind = "method" if is_method else "function"
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    node_id = f"{rel_path}#{qname}"
                    is_async = node.type == "async_function_definition"

                    params = node.child_by_field_name("parameters")
                    sig_params = self._get_node_text(params, source) if params else "()"
                    sig = f"{'async ' if is_async else ''}def {name}{sig_params}"

                    ret_type_node = node.child_by_field_name("return_type")
                    ret_type = self._get_node_text(ret_type_node, source) if ret_type_node else None

                    # Docstring
                    body = node.child_by_field_name("body")
                    docstring = self._extract_docstring(body, source)

                    s_line, e_line, s_col, e_col = self._get_point(node)
                    sym = ParsedSymbol(
                        id=node_id,
                        kind=kind,
                        name=name,
                        qualified_name=qname,
                        file_path=rel_path,
                        language="python",
                        start_line=s_line,
                        end_line=e_line,
                        start_column=s_col,
                        end_column=e_col,
                        docstring=docstring,
                        signature=sig,
                        is_async=is_async,
                        return_type=ret_type,
                        parent_id=parent_id,
                    )
                    symbols.append(sym)

                    if body:
                        for child in body.children:
                            visit(child, [*current_scope, name], node_id)
                    return

            # Imports: import x, y; from x import y
            elif node.type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        mod_name = self._get_node_text(child, source)
                        leaf = mod_name.split(".")[-1]
                        unresolved.append(
                            UnresolvedRef(
                                caller_id=parent_id or file_symbol_id,
                                target_name=leaf,
                                kind="imports",
                                file_path=rel_path,
                                line=int(child.start_point[0]) + 1,
                                col=int(child.start_point[1]),
                                import_source=mod_name,
                            )
                        )
            elif node.type == "import_from_statement":
                mod_node = node.child_by_field_name("module_name")
                mod_name = self._get_node_text(mod_node, source) if mod_node else None
                for child in node.children:
                    if child.type == "dotted_name" and child != mod_node:
                        sym_name = self._get_node_text(child, source)
                        unresolved.append(
                            UnresolvedRef(
                                caller_id=parent_id or file_symbol_id,
                                target_name=sym_name,
                                kind="imports",
                                file_path=rel_path,
                                line=int(child.start_point[0]) + 1,
                                col=int(child.start_point[1]),
                                import_source=mod_name,
                            )
                        )

            # Function calls
            elif node.type == "call":
                func_node = node.child_by_field_name("function")
                if func_node:
                    raw_name = self._get_node_text(func_node, source)
                    # Extract leaf name e.g. self.update() -> update; User.get() -> get
                    leaf_name = raw_name.split(".")[-1]
                    unresolved.append(
                        UnresolvedRef(
                            caller_id=parent_id or file_symbol_id,
                            target_name=leaf_name,
                            kind="calls",
                            file_path=rel_path,
                            line=int(func_node.start_point[0]) + 1,
                            col=int(func_node.start_point[1]),
                        )
                    )

            # Recurse generic children
            for child in node.children:
                visit(child, current_scope, parent_id)

        visit(root, [], None)

    def _extract_typescript(
        self,
        root: Any,
        source: bytes,
        rel_path: str,
        language: str,
        symbols: list[ParsedSymbol],
        unresolved: list[UnresolvedRef],
    ) -> None:
        file_symbol_id = f"{rel_path}#"

        def visit(node: Any, current_scope: list[str], parent_id: str | None) -> None:
            # Classes & Interfaces
            if node.type in ("class_declaration", "interface_declaration", "enum_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    kind_map = {
                        "class_declaration": "class",
                        "interface_declaration": "interface",
                        "enum_declaration": "enum",
                    }
                    kind = kind_map[node.type]
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    node_id = f"{rel_path}#{qname}"

                    s_line, e_line, s_col, e_col = self._get_point(node)
                    sym = ParsedSymbol(
                        id=node_id,
                        kind=kind,
                        name=name,
                        qualified_name=qname,
                        file_path=rel_path,
                        language=language,
                        start_line=s_line,
                        end_line=e_line,
                        start_column=s_col,
                        end_column=e_col,
                        signature=f"{kind} {name}",
                        parent_id=parent_id,
                    )
                    symbols.append(sym)

                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            visit(child, [*current_scope, name], node_id)
                    return

            # Function or Method
            elif node.type in ("function_declaration", "method_definition"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    is_method = node.type == "method_definition" or bool(current_scope)
                    kind = "method" if is_method else "function"
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    node_id = f"{rel_path}#{qname}"

                    params = node.child_by_field_name("parameters")
                    sig_params = self._get_node_text(params, source) if params else "()"

                    s_line, e_line, s_col, e_col = self._get_point(node)
                    sym = ParsedSymbol(
                        id=node_id,
                        kind=kind,
                        name=name,
                        qualified_name=qname,
                        file_path=rel_path,
                        language=language,
                        start_line=s_line,
                        end_line=e_line,
                        start_column=s_col,
                        end_column=e_col,
                        signature=f"{name}{sig_params}",
                        parent_id=parent_id,
                    )
                    symbols.append(sym)

                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            visit(child, [*current_scope, name], node_id)
                    return

            # Imports
            elif node.type == "import_statement":
                source_node = node.child_by_field_name("source")
                import_src = self._get_node_text(source_node, source).strip("'\"") if source_node else None
                for child in node.children:
                    if child.type == "import_clause":
                        for sub in child.children:
                            if sub.type in ("identifier", "import_specifier"):
                                sub_name = self._get_node_text(sub, source).split(" as ")[0].strip()
                                unresolved.append(
                                    UnresolvedRef(
                                        caller_id=parent_id or file_symbol_id,
                                        target_name=sub_name,
                                        kind="imports",
                                        file_path=rel_path,
                                        line=int(sub.start_point[0]) + 1,
                                        col=int(sub.start_point[1]),
                                        import_source=import_src,
                                    )
                                )

            # Calls & New expressions
            elif node.type in ("call_expression", "new_expression"):
                fn_node = node.child_by_field_name("function") or node.child_by_field_name("constructor")
                if fn_node:
                    raw_name = self._get_node_text(fn_node, source)
                    leaf = raw_name.split(".")[-1]
                    unresolved.append(
                        UnresolvedRef(
                            caller_id=parent_id or file_symbol_id,
                            target_name=leaf,
                            kind="instantiates" if node.type == "new_expression" else "calls",
                            file_path=rel_path,
                            line=int(fn_node.start_point[0]) + 1,
                            col=int(fn_node.start_point[1]),
                        )
                    )

            for child in node.children:
                visit(child, current_scope, parent_id)

        visit(root, [], None)

    def _extract_swift(
        self,
        root: Any,
        source: bytes,
        rel_path: str,
        symbols: list[ParsedSymbol],
        unresolved: list[UnresolvedRef],
    ) -> None:
        file_symbol_id = f"{rel_path}#"

        def _resolve_swift_decl_kind(node: Any) -> str:
            if node.type == "protocol_declaration":
                return "protocol"
            if node.type == "struct_declaration":
                return "struct"
            if node.type == "enum_declaration":
                return "enum"
            # In tree-sitter-swift, class_declaration covers class, struct, enum, extension, and actor
            decl_kind = node.child_by_field_name("declaration_kind")
            if decl_kind:
                k = decl_kind.type.lower()
                if k in ("struct", "enum", "class", "protocol", "extension"):
                    return k
                if k == "actor":
                    return "class"
            for child in node.children:
                c_type = child.type.lower()
                if c_type in ("struct", "enum", "class", "protocol", "extension"):
                    return c_type
                if c_type == "actor":
                    return "class"
            return "class"

        def visit(node: Any, current_scope: list[str], parent_id: str | None) -> None:
            # Swift struct, class, enum, protocol, extension
            if node.type in ("class_declaration", "struct_declaration", "enum_declaration", "protocol_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    if name_node.type == "user_type" and name_node.children:
                        name = self._get_node_text(name_node.children[0], source)
                    kind = _resolve_swift_decl_kind(node)
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    s_line, e_line, s_col, e_col = self._get_point(node)
                    if kind == "extension":
                        node_id = f"{rel_path}#extension.{qname}:{s_line}"
                        signature = f"extension {name}"
                    else:
                        node_id = f"{rel_path}#{qname}"
                        signature = f"{kind} {name}"

                    sym = ParsedSymbol(
                        id=node_id,
                        kind=kind,
                        name=name,
                        qualified_name=qname,
                        file_path=rel_path,
                        language="swift",
                        start_line=s_line,
                        end_line=e_line,
                        start_column=s_col,
                        end_column=e_col,
                        signature=signature,
                        parent_id=parent_id,
                    )
                    symbols.append(sym)

                    body = node.child_by_field_name("body")
                    if not body:
                        for child in node.children:
                            if child.type in ("class_body", "enum_class_body", "protocol_body"):
                                body = child
                                break
                    if body:
                        for child in body.children:
                            visit(child, [*current_scope, name], node_id)
                    return

            # Function or Method
            elif node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    is_method = bool(current_scope)
                    kind = "method" if is_method else "function"
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    node_id = f"{rel_path}#{qname}"

                    s_line, e_line, s_col, e_col = self._get_point(node)
                    sym = ParsedSymbol(
                        id=node_id,
                        kind=kind,
                        name=name,
                        qualified_name=qname,
                        file_path=rel_path,
                        language="swift",
                        start_line=s_line,
                        end_line=e_line,
                        start_column=s_col,
                        end_column=e_col,
                        signature=f"func {name}()",
                        parent_id=parent_id,
                    )
                    symbols.append(sym)

                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            visit(child, [*current_scope, name], node_id)
                    return

            # Swift calls
            elif node.type == "call_expression":
                # First child is usually the function/callee
                if node.children:
                    callee = node.children[0]
                    raw_name = self._get_node_text(callee, source)
                    leaf = raw_name.split(".")[-1]
                    unresolved.append(
                        UnresolvedRef(
                            caller_id=parent_id or file_symbol_id,
                            target_name=leaf,
                            kind="calls",
                            file_path=rel_path,
                            line=int(callee.start_point[0]) + 1,
                            col=int(callee.start_point[1]),
                        )
                    )

            for child in node.children:
                visit(child, current_scope, parent_id)

        visit(root, [], None)

    def _extract_dart(
        self,
        root: Any,
        source: bytes,
        rel_path: str,
        symbols: list[ParsedSymbol],
        unresolved: list[UnresolvedRef],
    ) -> None:
        def visit(node: Any, current_scope: list[str], parent_id: str | None) -> None:
            if node.type in ("class_definition", "enum_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    kind = "class" if node.type == "class_definition" else "enum"
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    node_id = f"{rel_path}#{qname}"

                    s_line, e_line, s_col, e_col = self._get_point(node)
                    sym = ParsedSymbol(
                        id=node_id,
                        kind=kind,
                        name=name,
                        qualified_name=qname,
                        file_path=rel_path,
                        language="dart",
                        start_line=s_line,
                        end_line=e_line,
                        start_column=s_col,
                        end_column=e_col,
                        signature=f"{kind} {name}",
                        parent_id=parent_id,
                    )
                    symbols.append(sym)

                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            visit(child, [*current_scope, name], node_id)
                    return

            elif node.type in ("method_signature", "function_signature"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    kind = "method" if bool(current_scope) else "function"
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    node_id = f"{rel_path}#{qname}"

                    s_line, e_line, s_col, e_col = self._get_point(node)
                    sym = ParsedSymbol(
                        id=node_id,
                        kind=kind,
                        name=name,
                        qualified_name=qname,
                        file_path=rel_path,
                        language="dart",
                        start_line=s_line,
                        end_line=e_line,
                        start_column=s_col,
                        end_column=e_col,
                        signature=f"{name}()",
                        parent_id=parent_id,
                    )
                    symbols.append(sym)

            for child in node.children:
                visit(child, current_scope, parent_id)

        visit(root, [], None)

    def _extract_generic(
        self,
        root: Any,
        source: bytes,
        rel_path: str,
        language: str,
        symbols: list[ParsedSymbol],
        unresolved: list[UnresolvedRef],
    ) -> None:
        """Generic fallback extractor inspecting typical AST node patterns."""

        def visit(node: Any, current_scope: list[str], parent_id: str | None) -> None:
            ntype = node.type.lower()
            if "class" in ntype or "struct" in ntype or "interface" in ntype:
                name_node = node.child_by_field_name("name") or (node.children[0] if node.children else None)
                if name_node and name_node.type == "identifier":
                    name = self._get_node_text(name_node, source)
                    kind = "class" if "class" in ntype else ("struct" if "struct" in ntype else "interface")
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    node_id = f"{rel_path}#{qname}"
                    s_line, e_line, s_col, e_col = self._get_point(node)
                    symbols.append(
                        ParsedSymbol(
                            id=node_id,
                            kind=kind,
                            name=name,
                            qualified_name=qname,
                            file_path=rel_path,
                            language=language,
                            start_line=s_line,
                            end_line=e_line,
                            start_column=s_col,
                            end_column=e_col,
                            signature=f"{kind} {name}",
                            parent_id=parent_id,
                        )
                    )
                    for child in node.children:
                        visit(child, [*current_scope, name], node_id)
                    return

            elif "function" in ntype or "method" in ntype:
                name_node = node.child_by_field_name("name") or (node.children[0] if node.children else None)
                if name_node and name_node.type == "identifier":
                    name = self._get_node_text(name_node, source)
                    kind = "method" if bool(current_scope) else "function"
                    qname = ".".join([*current_scope, name]) if current_scope else name
                    node_id = f"{rel_path}#{qname}"
                    s_line, e_line, s_col, e_col = self._get_point(node)
                    symbols.append(
                        ParsedSymbol(
                            id=node_id,
                            kind=kind,
                            name=name,
                            qualified_name=qname,
                            file_path=rel_path,
                            language=language,
                            start_line=s_line,
                            end_line=e_line,
                            start_column=s_col,
                            end_column=e_col,
                            signature=f"{name}()",
                            parent_id=parent_id,
                        )
                    )
                    for child in node.children:
                        visit(child, [*current_scope, name], node_id)
                    return

            for child in node.children:
                visit(child, current_scope, parent_id)

        visit(root, [], None)

    # -------------------------------------------------------------------------
    # PASS 2: Two-Pass Linker
    # -------------------------------------------------------------------------

    def link_symbols(
        self,
        all_symbols: list[ParsedSymbol],
        all_unresolved: list[UnresolvedRef],
    ) -> list[tuple[str, str, str, str | None, int | None, int | None, str | None]]:
        """Link unresolved references into graph edges with 3-tier scoping."""
        # Index lookups
        by_name: dict[str, list[ParsedSymbol]] = {}
        by_qualified_name: dict[str, ParsedSymbol] = {}
        by_file: dict[str, list[ParsedSymbol]] = {}
        file_to_imports: dict[str, list[UnresolvedRef]] = {}

        for sym in all_symbols:
            by_name.setdefault(sym.name, []).append(sym)
            by_qualified_name[sym.qualified_name] = sym
            by_file.setdefault(sym.file_path, []).append(sym)

        for ref in all_unresolved:
            if ref.kind == "imports":
                file_to_imports.setdefault(ref.file_path, []).append(ref)

        edges: list[tuple[str, str, str, str | None, int | None, int | None, str | None]] = []

        # 1. Structural 'contains' edges (Parent -> Child)
        for sym in all_symbols:
            if sym.parent_id:
                edges.append((sym.parent_id, sym.id, "contains", None, sym.start_line, sym.start_column, "syntax"))

        # 2. Reference resolution
        for ref in all_unresolved:
            target_node: ParsedSymbol | None = None
            provenance = "unresolved"

            # Tier 1: Local Scope (same file)
            local_matches = [s for s in by_file.get(ref.file_path, []) if s.name == ref.target_name]
            if local_matches:
                target_node = local_matches[0]
                provenance = "local_scope"

            # Tier 2: Explicit Imports
            if not target_node and ref.file_path in file_to_imports:
                for imp in file_to_imports[ref.file_path]:
                    if imp.target_name == ref.target_name:
                        # Match with external symbols
                        candidates = by_name.get(ref.target_name, [])
                        for cand in candidates:
                            if cand.file_path != ref.file_path:
                                target_node = cand
                                provenance = "explicit_import"
                                break
                    if target_node:
                        break

            # Tier 3: Global Project Scope (Exact unique name or directory proximity)
            if not target_node:
                global_matches = by_name.get(ref.target_name, [])
                if len(global_matches) == 1:
                    target_node = global_matches[0]
                    provenance = "global_unique"
                elif len(global_matches) > 1:
                    # Prefer same folder
                    ref_dir = Path(ref.file_path).parent
                    same_dir = [m for m in global_matches if Path(m.file_path).parent == ref_dir]
                    if same_dir:
                        target_node = same_dir[0]
                        provenance = "global_proximity"
                    else:
                        target_node = global_matches[0]
                        provenance = "global_ambiguous"

            if target_node and target_node.id != ref.caller_id:
                edges.append((ref.caller_id, target_node.id, ref.kind, None, ref.line, ref.col, provenance))

        return edges

    # -------------------------------------------------------------------------
    # MAIN PIPELINE & INCREMENTAL SYNC
    # -------------------------------------------------------------------------

    def index(self, force: bool = False) -> IndexResult:
        """Run incremental or full code graph indexing pipeline."""
        start_time = time.perf_counter()
        result = IndexResult(project_root=str(self.project_root), db_path=str(self.db_path))

        conn = self.init_db(force=force)
        cur = conn.cursor()

        # Load existing files state
        existing_files: dict[str, tuple[str, int]] = {}
        if not force:
            cur.execute("SELECT path, content_hash, modified_at FROM files")
            for row in cur.fetchall():
                existing_files[row["path"]] = (row["content_hash"], row["modified_at"])

        discovered = self.discover_files()
        current_paths: set[str] = set()

        files_to_parse: list[tuple[Path, str, str, str, int, int]] = []

        for fpath, rel_path, lang in discovered:
            current_paths.add(rel_path)
            try:
                chash, size, mtime = self._hash_file(fpath)
            except Exception as e:
                result.errors.append(f"Hash error on {rel_path}: {e}")
                continue

            if not force and rel_path in existing_files:
                old_hash, old_mtime = existing_files[rel_path]
                if old_hash == chash and old_mtime == mtime:
                    result.files_skipped += 1
                    continue

            files_to_parse.append((fpath, rel_path, lang, chash, size, mtime))

        # Deleted files cleanup
        deleted_paths = set(existing_files.keys()) - current_paths
        if deleted_paths:
            for dpath in deleted_paths:
                cur.execute(
                    "DELETE FROM edges WHERE source LIKE ? OR target LIKE ? OR provenance = ?",
                    (f"{dpath}#%", f"{dpath}#%", dpath),
                )
                cur.execute("DELETE FROM nodes WHERE file_path = ?", (dpath,))
                cur.execute("DELETE FROM files WHERE path = ?", (dpath,))
                result.files_deleted += 1

        # Incremental clean for modified files
        for _, rel_path, _, _, _, _ in files_to_parse:
            cur.execute(
                "DELETE FROM edges WHERE source LIKE ? OR target LIKE ? OR provenance = ?",
                (f"{rel_path}#%", f"{rel_path}#%", rel_path),
            )
            cur.execute("DELETE FROM nodes WHERE file_path = ?", (rel_path,))
            cur.execute("DELETE FROM files WHERE path = ?", (rel_path,))

        conn.commit()

        # Pass 1: Parse AST for new/modified files
        all_parsed_symbols: list[ParsedSymbol] = []
        all_unresolved: list[UnresolvedRef] = []
        now_ts = int(time.time())

        for fpath, rel_path, lang, chash, size, mtime in files_to_parse:
            symbols, unresolved, err = self.parse_file(fpath, rel_path, lang)
            if err:
                result.errors.append(f"{rel_path}: {err}")

            all_parsed_symbols.extend(symbols)
            all_unresolved.extend(unresolved)

            cur.execute(
                """
                INSERT OR REPLACE INTO files (
                    path, content_hash, language, size, modified_at, indexed_at, node_count, errors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rel_path, chash, lang, size, mtime, now_ts, len(symbols), err),
            )
            result.files_indexed += 1

        # If incremental, we also need existing symbols to properly link inter-file calls
        if not force and existing_files:
            cur.execute("SELECT * FROM nodes")
            for row in cur.fetchall():
                # Reconstruct light symbol for linking
                all_parsed_symbols.append(
                    ParsedSymbol(
                        id=row["id"],
                        kind=row["kind"],
                        name=row["name"],
                        qualified_name=row["qualified_name"],
                        file_path=row["file_path"],
                        language=row["language"],
                        start_line=row["start_line"],
                        end_line=row["end_line"],
                        signature=row["signature"],
                    )
                )

        # Batch insert nodes
        nodes_data = [
            (
                s.id,
                s.kind,
                s.name,
                s.qualified_name,
                s.file_path,
                s.language,
                s.start_line,
                s.end_line,
                s.start_column,
                s.end_column,
                s.docstring,
                s.signature,
                s.visibility,
                int(s.is_exported),
                int(s.is_async),
                int(s.is_static),
                int(s.is_abstract),
                json.dumps(s.decorators) if s.decorators else None,
                s.type_parameters,
                s.return_type,
                now_ts,
            )
            for s in all_parsed_symbols
            if any(s.file_path == f[1] for f in files_to_parse)  # only new ones
        ]

        if nodes_data:
            cur.executemany(
                """
                INSERT OR REPLACE INTO nodes (
                    id, kind, name, qualified_name, file_path, language,
                    start_line, end_line, start_column, end_column, docstring,
                    signature, visibility, is_exported, is_async, is_static,
                    is_abstract, decorators, type_parameters, return_type, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                nodes_data,
            )

        # Pass 2: Link symbols into edges
        edges = self.link_symbols(all_parsed_symbols, all_unresolved)
        if edges:
            cur.executemany(
                """
                INSERT INTO edges (source, target, kind, metadata, line, col, provenance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                edges,
            )

        # Update metadata
        cur.execute("SELECT count(*) FROM nodes")
        result.nodes_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM edges")
        result.edges_count = cur.fetchone()[0]

        cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '1.0.0')")
        cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('last_indexed', ?)", (str(now_ts),))
        cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('generator', 'personal-kb-native-tree-sitter')")

        # Sync schema_versions for Volta codegraph CLI compatibility
        cur.execute("INSERT OR IGNORE INTO schema_versions (version, applied_at) VALUES (5, ?)", (now_ts,))

        conn.commit()
        conn.close()

        result.duration_seconds = time.perf_counter() - start_time
        if self.db_path.exists():
            result.db_size_bytes = self.db_path.stat().st_size

        return result
