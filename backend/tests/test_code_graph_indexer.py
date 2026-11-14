"""Unit and integration tests for CodeGraphIndexer and native tree-sitter ingestion."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer

from personal_kb.cli import main as cli_main
from personal_kb.mcp.code_tools import register_code_tools
from personal_kb.services.code_graph_indexer import CodeGraphIndexer
from personal_kb.services.code_graph_reader import CodeGraphReader


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project folder with multi-language sample files."""
    proj = tmp_path / "sample_project"
    proj.mkdir()

    # Module A: models.py
    (proj / "models.py").write_text(
        '''"""User models module."""

class User:
    """Represents a registered system user."""

    def __init__(self, username: str):
        self.username = username

    def activate(self) -> bool:
        """Activate the user account."""
        return True
''',
        encoding="utf-8",
    )

    # Module B: service.py
    (proj / "service.py").write_text(
        '''"""User service module."""
from models import User

class UserService:
    def __init__(self):
        self.active_user = None

    async def register_user(self, name: str) -> User:
        user = User(name)
        user.activate()
        return user
''',
        encoding="utf-8",
    )

    # TypeScript sample
    (proj / "index.ts").write_text(
        """interface AppConfig {
    port: number;
}

class Server {
    start(): void {
        this.listen();
    }

    listen(): void {}
}
""",
        encoding="utf-8",
    )

    return proj


def test_tree_sitter_python_extraction(temp_project: Path):
    """Test AST extraction of classes, methods, functions, and docstrings in Python."""
    indexer = CodeGraphIndexer(temp_project)
    res = indexer.index(force=True)

    assert res.files_indexed == 3
    assert res.nodes_count >= 6
    assert res.edges_count >= 3

    conn = sqlite3.connect(res.db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check User class node
    cur.execute("SELECT * FROM nodes WHERE name = 'User' AND kind = 'class'")
    user_row = cur.fetchone()
    assert user_row is not None
    assert user_row["file_path"] == "models.py"
    assert user_row["docstring"] == "Represents a registered system user."

    # Check activate method
    cur.execute("SELECT * FROM nodes WHERE name = 'activate' AND kind = 'method'")
    act_row = cur.fetchone()
    assert act_row is not None
    assert act_row["qualified_name"] == "User.activate"
    assert act_row["docstring"] == "Activate the user account."

    conn.close()


def test_tree_sitter_typescript_extraction(temp_project: Path):
    """Test AST extraction of interfaces and classes in TypeScript."""
    indexer = CodeGraphIndexer(temp_project)
    res = indexer.index(force=True)

    conn = sqlite3.connect(res.db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM nodes WHERE name = 'AppConfig'")
    cfg_row = cur.fetchone()
    assert cfg_row is not None
    assert cfg_row["kind"] == "interface"
    assert cfg_row["file_path"] == "index.ts"

    cur.execute("SELECT * FROM nodes WHERE name = 'Server'")
    srv_row = cur.fetchone()
    assert srv_row is not None
    assert srv_row["kind"] == "class"

    conn.close()


def test_two_pass_linker_inter_file_calls(temp_project: Path):
    """Test that function calls across files are resolved via Two-Pass Linker."""
    indexer = CodeGraphIndexer(temp_project)
    res = indexer.index(force=True)

    conn = sqlite3.connect(res.db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check contains edges (User -> activate)
    cur.execute(
        """
        SELECT * FROM edges
        WHERE source = 'models.py#User' AND target = 'models.py#User.activate' AND kind = 'contains'
        """
    )
    assert cur.fetchone() is not None

    # Check call edge from register_user to activate
    cur.execute(
        """
        SELECT * FROM edges
        WHERE source = 'service.py#UserService.register_user'
          AND target = 'models.py#User.activate'
          AND kind = 'calls'
        """
    )
    call_edge = cur.fetchone()
    assert call_edge is not None
    assert call_edge["provenance"] in ("explicit_import", "global_unique", "global_proximity")

    conn.close()


def test_incremental_indexing(temp_project: Path):
    """Test incremental indexing skips unchanged files and re-indexes modified files."""
    indexer = CodeGraphIndexer(temp_project)

    # First run (full)
    res1 = indexer.index(force=True)
    assert res1.files_indexed == 3
    assert res1.files_skipped == 0

    # Second run without changes
    res2 = indexer.index(force=False)
    assert res2.files_indexed == 0
    assert res2.files_skipped == 3

    # Modify models.py
    models_file = temp_project / "models.py"
    models_file.write_text(models_file.read_text(encoding="utf-8") + "\n\ndef standalone(): pass\n", encoding="utf-8")

    # Third run: only models.py should be re-indexed
    res3 = indexer.index(force=False)
    assert res3.files_indexed == 1
    assert res3.files_skipped == 2

    conn = sqlite3.connect(res3.db_path)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM nodes WHERE name = 'standalone'")
    assert cur.fetchone()[0] == 1
    conn.close()


def test_orphan_cleanup_on_file_deletion(temp_project: Path):
    """Test deleting a file cleans up its nodes and edges in SQLite and FTS5."""
    indexer = CodeGraphIndexer(temp_project)
    res1 = indexer.index(force=True)
    assert res1.files_indexed == 3

    # Delete index.ts
    (temp_project / "index.ts").unlink()

    # Re-index
    res2 = indexer.index(force=False)
    assert res2.files_deleted == 1

    conn = sqlite3.connect(res2.db_path)
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM nodes WHERE file_path = 'index.ts'")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT count(*) FROM nodes_fts WHERE name = 'AppConfig'")
    assert cur.fetchone()[0] == 0

    conn.close()


def test_backward_compatibility_with_code_graph_reader(temp_project: Path):
    """Test that databases produced by native CodeGraphIndexer work 100% with CodeGraphReader."""
    indexer = CodeGraphIndexer(temp_project)
    res = indexer.index(force=True)

    reader = CodeGraphReader(res.db_path)
    assert reader.is_available

    status = reader.get_status()
    assert status.available
    assert status.node_count >= 6
    assert status.edge_count >= 3

    # Test FTS5 search
    search_res = reader.search_symbols("User")
    assert len(search_res) >= 1
    assert any(n.name == "User" for n in search_res)

    # Test get_node and snippet
    user_node = reader.get_node("User")
    assert user_node is not None
    assert user_node.kind == "class"
    assert user_node.file_path == "models.py"

    snippet = reader.read_code_snippet(user_node)
    assert snippet is not None
    assert "class User:" in snippet

    # Test get_callers on activate
    callers = reader.get_callers("activate")
    assert len(callers) >= 1
    assert callers[0].node.name == "register_user"

    # Test get_impact on User
    impact = reader.get_impact("User", max_depth=2)
    assert len(impact.focal_nodes) == 1
    assert len(impact.impacted_nodes) >= 1


def test_cli_index_code_invocation(temp_project: Path):
    """Test invoking personal-kb CLI index-code command."""
    code = cli_main(["index-code", str(temp_project), "--force", "--quiet"])
    assert code == 0

    db_path = temp_project / ".codegraph" / "codegraph.db"
    assert db_path.is_file()


@pytest.mark.asyncio
async def test_mcp_tool_kb_code_index(temp_project: Path):
    """Test invoking kb_code_index via MCP server."""
    server = MCPServer(name="test-server")
    register_code_tools(server)

    res = await server.call_tool("kb_code_index", {"project_path": str(temp_project), "force": True})
    assert not res.is_error
    text = res.content[0].text
    assert "Quét và Lập Chỉ Mục CodeGraph Thành Công" in text
    assert "DB Path:" in text


def test_tree_sitter_swift_struct_enum_class_kinds(tmp_path: Path):
    """Test extracting exact symbol kinds for Swift struct, enum, class, and protocol."""
    swift_file = tmp_path / "Sample.swift"
    swift_file.write_text(
        """
struct Point {
    var x: Int
    func distance() -> Int { return x }
}

enum Direction: String {
    case north, south
    func describe() -> String { return "dir" }
}

class Controller {
    func handle() {}
}

protocol Describable {
    func info()
}
""",
        encoding="utf-8",
    )

    indexer = CodeGraphIndexer(tmp_path)
    res = indexer.index(force=True)
    assert res.files_indexed == 1

    conn = sqlite3.connect(res.db_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT name, kind, signature FROM nodes "
        "WHERE language = 'swift' AND kind IN ('struct', 'enum', 'class', 'protocol')"
    )
    rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    conn.close()

    assert "Point" in rows, f"Point missing from rows: {rows}"
    assert rows["Point"][0] == "struct"
    assert rows["Point"][1].startswith("struct ")

    assert "Direction" in rows, f"Direction missing from rows: {rows}"
    assert rows["Direction"][0] == "enum"
    assert rows["Direction"][1].startswith("enum ")

    assert "Controller" in rows, f"Controller missing from rows: {rows}"
    assert rows["Controller"][0] == "class"
    assert rows["Controller"][1].startswith("class ")

    assert "Describable" in rows, f"Describable missing from rows: {rows}"
    assert rows["Describable"][0] == "protocol"
    assert rows["Describable"][1].startswith("protocol ")


def test_tree_sitter_swift_enum_and_struct_members(tmp_path: Path):
    """Test methods inside enums and structs, nested types, and containment edges."""
    swift_file = tmp_path / "Nested.swift"
    swift_file.write_text(
        """
enum Outer {
    case active
    func outerMethod() {}

    struct Inner {
        var val: Int
        func innerMethod() {}
    }
}

struct Model {
    func execute() {}
}
""",
        encoding="utf-8",
    )

    indexer = CodeGraphIndexer(tmp_path)
    res = indexer.index(force=True)
    assert res.files_indexed == 1

    conn = sqlite3.connect(res.db_path)
    cur = conn.cursor()

    # Query nodes
    cur.execute("SELECT qualified_name, kind FROM nodes WHERE language = 'swift'")
    nodes = {r[0]: r[1] for r in cur.fetchall()}

    assert nodes.get("Outer") == "enum"
    assert nodes.get("Outer.outerMethod") == "method"
    assert nodes.get("Outer.Inner") == "struct"
    assert nodes.get("Outer.Inner.innerMethod") == "method"
    assert nodes.get("Model") == "struct"
    assert nodes.get("Model.execute") == "method"

    # Query contains edges
    cur.execute("SELECT source, target, kind FROM edges WHERE kind = 'contains'")
    edges = {(r[0], r[1]) for r in cur.fetchall()}
    conn.close()

    assert any(target.endswith("#Outer.outerMethod") for source, target in edges)
    assert any(target.endswith("#Outer.Inner") for source, target in edges)
    assert any(target.endswith("#Model.execute") for source, target in edges)


def test_tree_sitter_swift_extension_does_not_overwrite_protocol_or_struct(tmp_path: Path):
    """Test Swift extension coexists with protocol or struct in same file without collision."""
    swift_file = tmp_path / "Coexist.swift"
    swift_file.write_text(
        """
public protocol WorkerProtocol: AnyObject {
    func doWork()
}

public extension WorkerProtocol {
    func defaultHelper() {}
}

public struct WorkerConfig {
    var id: String
}

public extension WorkerConfig {
    func format() -> String { return id }
}
""",
        encoding="utf-8",
    )

    indexer = CodeGraphIndexer(tmp_path)
    res = indexer.index(force=True)
    assert res.files_indexed == 1

    conn = sqlite3.connect(res.db_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT name, kind, signature FROM nodes "
        "WHERE language = 'swift' AND name IN ('WorkerProtocol', 'WorkerConfig')"
    )
    symbols = cur.fetchall()
    conn.close()

    kinds = {(s[0], s[1]) for s in symbols}
    assert ("WorkerProtocol", "protocol") in kinds
    assert ("WorkerProtocol", "extension") in kinds
    assert ("WorkerConfig", "struct") in kinds
    assert ("WorkerConfig", "extension") in kinds
