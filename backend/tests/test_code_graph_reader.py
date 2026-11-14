"""Unit & integration tests for CodeGraph SQLite Reader Adapter and MCP tools."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from personal_kb.mcp.server import create_mcp_server
from personal_kb.services.code_graph_reader import (
    CodeGraphReader,
    resolve_db_path,
)


@pytest.fixture
def sample_codegraph_db(tmp_path: Path) -> Path:
    """Create a temporary mock CodeGraph SQLite database with source files on disk."""
    project_root = tmp_path / "mock_project"
    project_root.mkdir(parents=True, exist_ok=True)
    src_dir = project_root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create source code files on disk
    api_file = src_dir / "api.py"
    api_file.write_text(
        "def api_calculate_payroll(request):\n"
        "    '''Entrypoint API for payroll calculation.'''\n"
        "    net = calculate_net_pay(1000)\n"
        "    return {'net': net}\n",
        encoding="utf-8",
    )

    payroll_file = src_dir / "payroll.py"
    payroll_file.write_text(
        "def calculate_net_pay(salary):\n"
        "    '''Calculate net pay after tax deduction.'''\n"
        "    tax = compute_pit_tax(salary)\n"
        "    total = salary - tax\n"
        "    return round_currency(total)\n",
        encoding="utf-8",
    )

    tax_file = src_dir / "tax.py"
    tax_file.write_text(
        "def compute_pit_tax(salary):\n"
        "    '''Compute Personal Income Tax.'''\n"
        "    return salary * 0.1\n\n"
        "class TaxReport:\n"
        "    '''Report summary of taxes.'''\n"
        "    pass\n",
        encoding="utf-8",
    )

    utils_file = src_dir / "utils.py"
    utils_file.write_text(
        "def round_currency(amount):\n"
        "    '''Round monetary amount to integer.'''\n"
        "    return int(amount)\n",
        encoding="utf-8",
    )

    # 2. Create SQLite DB inside .codegraph/
    db_dir = project_root / ".codegraph"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "codegraph.db"

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            qualified_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            language TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            start_column INTEGER NOT NULL DEFAULT 0,
            end_column INTEGER NOT NULL DEFAULT 0,
            docstring TEXT,
            signature TEXT,
            visibility TEXT DEFAULT 'public',
            is_exported INTEGER DEFAULT 0,
            is_async INTEGER DEFAULT 0,
            is_static INTEGER DEFAULT 0,
            is_abstract INTEGER DEFAULT 0,
            decorators TEXT DEFAULT '[]',
            type_parameters TEXT DEFAULT '[]',
            return_type TEXT,
            updated_at INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            kind TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            line INTEGER,
            col INTEGER,
            provenance TEXT DEFAULT 'tree-sitter'
        );

        CREATE TABLE files (
            path TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            language TEXT NOT NULL,
            size INTEGER NOT NULL,
            modified_at INTEGER NOT NULL,
            indexed_at INTEGER NOT NULL,
            node_count INTEGER DEFAULT 0,
            errors TEXT DEFAULT '[]'
        );

        CREATE VIRTUAL TABLE nodes_fts USING fts5(
            id,
            name,
            qualified_name,
            docstring,
            signature,
            content='nodes',
            content_rowid='rowid'
        );

        CREATE TRIGGER nodes_ai AFTER INSERT ON nodes BEGIN
            INSERT INTO nodes_fts(rowid, id, name, qualified_name, docstring, signature)
            VALUES (NEW.rowid, NEW.id, NEW.name, NEW.qualified_name, NEW.docstring, NEW.signature);
        END;
        """
    )

    # Insert files
    for p, lang, size in [
        ("src/api.py", "python", len(api_file.read_text())),
        ("src/payroll.py", "python", len(payroll_file.read_text())),
        ("src/tax.py", "python", len(tax_file.read_text())),
        ("src/utils.py", "python", len(utils_file.read_text())),
    ]:
        cur.execute(
            "INSERT INTO files (path, content_hash, language, size, modified_at, indexed_at) "
            "VALUES (?, 'hash123', ?, ?, 1000, 1000)",
            (p, lang, size),
        )

    # Insert nodes
    nodes_data = [
        (
            "node:api",
            "function",
            "api_calculate_payroll",
            "src/api.py::api_calculate_payroll",
            "src/api.py",
            "python",
            1,
            4,
            "Entrypoint API for payroll calculation.",
            "def api_calculate_payroll(request)",
            1,
        ),
        (
            "node:payroll",
            "function",
            "calculate_net_pay",
            "src/payroll.py::calculate_net_pay",
            "src/payroll.py",
            "python",
            1,
            5,
            "Calculate net pay after tax deduction.",
            "def calculate_net_pay(salary)",
            1,
        ),
        (
            "node:tax_func",
            "function",
            "compute_pit_tax",
            "src/tax.py::compute_pit_tax",
            "src/tax.py",
            "python",
            1,
            3,
            "Compute Personal Income Tax.",
            "def compute_pit_tax(salary)",
            1,
        ),
        (
            "node:tax_class",
            "class",
            "TaxReport",
            "src/tax.py::TaxReport",
            "src/tax.py",
            "python",
            5,
            7,
            "Report summary of taxes.",
            "class TaxReport",
            1,
        ),
        (
            "node:utils",
            "function",
            "round_currency",
            "src/utils.py::round_currency",
            "src/utils.py",
            "python",
            1,
            3,
            "Round monetary amount to integer.",
            "def round_currency(amount)",
            0,
        ),
    ]

    cur.executemany(
        """
        INSERT INTO nodes (
            id, kind, name, qualified_name, file_path, language,
            start_line, end_line, docstring, signature, is_exported
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        nodes_data,
    )

    # Insert edges
    # api -> calls -> payroll
    # payroll -> calls -> tax_func
    # payroll -> calls -> utils
    cur.execute(
        """
        INSERT INTO edges (source, target, kind, line)
        VALUES
        ('node:api', 'node:payroll', 'calls', 3),
        ('node:payroll', 'node:tax_func', 'calls', 3),
        ('node:payroll', 'node:utils', 'calls', 5);
        """
    )

    conn.commit()
    conn.close()

    return db_path


def test_resolve_db_path_walks_up_parents(sample_codegraph_db: Path) -> None:
    project_root = sample_codegraph_db.parent.parent
    sub_dir = project_root / "src" / "deep" / "nested"
    sub_dir.mkdir(parents=True, exist_ok=True)

    resolved = resolve_db_path(sub_dir)
    assert resolved is not None
    assert resolved.resolve() == sample_codegraph_db.resolve()

    # Pass db file directly
    assert resolve_db_path(sample_codegraph_db) == sample_codegraph_db.resolve()


def test_graceful_degradation_when_db_missing(tmp_path: Path) -> None:
    non_existent = tmp_path / "empty_dir"
    non_existent.mkdir()

    reader = CodeGraphReader(non_existent)
    assert not reader.is_available

    status = reader.get_status()
    assert not status.available
    assert "Không tìm thấy" in status.message

    assert reader.search_symbols("test") == []
    assert reader.get_node("test") is None
    assert reader.get_callers("test") == []
    assert reader.get_callees("test") == []

    impact = reader.get_impact("test")
    assert impact.focal_nodes == []
    assert impact.impacted_nodes == []


def test_get_status(sample_codegraph_db: Path) -> None:
    reader = CodeGraphReader(sample_codegraph_db)
    assert reader.is_available

    status = reader.get_status()
    assert status.available
    assert status.node_count == 5
    assert status.edge_count == 3
    assert status.file_count == 4
    assert status.nodes_by_kind.get("function") == 4
    assert status.nodes_by_kind.get("class") == 1
    assert status.files_by_language.get("python") == 4
    assert status.db_size_bytes > 0


def test_search_symbols_fts_and_filters(sample_codegraph_db: Path) -> None:
    reader = CodeGraphReader(sample_codegraph_db)

    # FTS5 search
    res = reader.search_symbols("payroll")
    assert len(res) >= 2
    names = {n.name for n in res}
    assert "api_calculate_payroll" in names
    assert "calculate_net_pay" in names

    # Filter by kind
    class_res = reader.search_symbols("Tax", kind="class")
    assert len(class_res) == 1
    assert class_res[0].name == "TaxReport"

    # Filter by language
    py_res = reader.search_symbols("round", language="python")
    assert len(py_res) == 1
    assert py_res[0].name == "round_currency"

    # Substring fallback
    sub_res = reader.search_symbols("pit")
    assert len(sub_res) == 1
    assert sub_res[0].name == "compute_pit_tax"


def test_get_node_with_and_without_code(sample_codegraph_db: Path) -> None:
    reader = CodeGraphReader(sample_codegraph_db)

    # By name
    node = reader.get_node("calculate_net_pay")
    assert node is not None
    assert node.id == "node:payroll"
    assert node.file_path == "src/payroll.py"
    assert node.start_line == 1
    assert node.end_line == 5

    # Read code snippet
    code = reader.read_code_snippet(node)
    assert code is not None
    assert "def calculate_net_pay" in code
    assert "round_currency" in code

    # By qualified name
    node2 = reader.get_node("src/tax.py::TaxReport")
    assert node2 is not None
    assert node2.name == "TaxReport"


def test_get_callers_and_callees(sample_codegraph_db: Path) -> None:
    reader = CodeGraphReader(sample_codegraph_db)

    # Callers of calculate_net_pay -> should be api_calculate_payroll
    callers = reader.get_callers("calculate_net_pay")
    assert len(callers) == 1
    assert callers[0].node.name == "api_calculate_payroll"
    assert callers[0].edge.line == 3

    # Callees of calculate_net_pay -> should be compute_pit_tax and round_currency
    callees = reader.get_callees("calculate_net_pay")
    assert len(callees) == 2
    callee_names = {c.node.name for c in callees}
    assert "compute_pit_tax" in callee_names
    assert "round_currency" in callee_names


def test_get_impact_transitive_bfs(sample_codegraph_db: Path) -> None:
    reader = CodeGraphReader(sample_codegraph_db)

    # Impact of changing compute_pit_tax:
    # Level 1 caller: calculate_net_pay (payroll.py)
    # Level 2 caller: api_calculate_payroll (api.py)
    report = reader.get_impact("compute_pit_tax", max_depth=2)

    assert len(report.focal_nodes) == 1
    assert report.focal_nodes[0].name == "compute_pit_tax"

    impacted_names = {n.name for n in report.impacted_nodes}
    assert "calculate_net_pay" in impacted_names
    assert "api_calculate_payroll" in impacted_names

    # By file grouping
    assert "src/payroll.py" in report.by_file
    assert "src/api.py" in report.by_file
    assert len(report.by_file) == 2

    # Depth 1 test
    report_d1 = reader.get_impact("compute_pit_tax", max_depth=1)
    d1_names = {n.name for n in report_d1.impacted_nodes}
    assert "calculate_net_pay" in d1_names
    assert "api_calculate_payroll" not in d1_names


def test_read_code_snippet_rejects_path_traversal(sample_codegraph_db: Path) -> None:
    reader = CodeGraphReader(sample_codegraph_db)
    malicious_node = reader.get_node("calculate_net_pay")
    assert malicious_node is not None

    # Replace file_path with path traversal attempt
    traversal_node = CodeGraphReader._clone_node_with_path(
        malicious_node,
        "../../outside.py",
    ) if hasattr(CodeGraphReader, "_clone_node_with_path") else CodeGraphReader(sample_codegraph_db)

    # Directly create malicious CodeNode
    from personal_kb.services.code_graph_reader import CodeNode
    traversal_node = CodeNode(
        id="malicious:id",
        kind="function",
        name="hack",
        qualified_name="outside::hack",
        file_path="../../outside.py",
        language="python",
        start_line=1,
        end_line=2,
    )
    assert reader.read_code_snippet(traversal_node) is None


def test_get_impact_container_expansion_and_cycle_safety(sample_codegraph_db: Path) -> None:
    # Add a class with a child method, and a circular caller cycle
    conn = sqlite3.connect(sample_codegraph_db)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO nodes (id, kind, name, qualified_name, file_path, language, start_line, end_line)
        VALUES
        ('node:order_service', 'class', 'OrderService', 'src/order.py::OrderService',
         'src/order.py', 'python', 1, 20),
        ('node:order_checkout', 'method', 'checkout', 'src/order.py::OrderService.checkout',
         'src/order.py', 'python', 5, 10),
        ('node:order_caller_a', 'function', 'caller_a', 'src/order.py::caller_a',
         'src/order.py', 'python', 22, 25),
        ('node:order_caller_b', 'function', 'caller_b', 'src/order.py::caller_b',
         'src/order.py', 'python', 27, 30);
        """
    )
    # OrderService contains checkout
    # caller_a calls checkout
    # caller_b calls caller_a
    # caller_a calls caller_b (circular cycle!)
    cur.execute(
        """
        INSERT INTO edges (source, target, kind)
        VALUES
        ('node:order_service', 'node:order_checkout', 'contains'),
        ('node:order_caller_a', 'node:order_checkout', 'calls'),
        ('node:order_caller_b', 'node:order_caller_a', 'calls'),
        ('node:order_caller_a', 'node:order_caller_b', 'calls');
        """
    )
    conn.commit()
    conn.close()

    reader = CodeGraphReader(sample_codegraph_db)
    report = reader.get_impact("OrderService", max_depth=3)

    assert len(report.focal_nodes) == 1
    assert report.focal_nodes[0].name == "OrderService"

    impacted_names = {n.name for n in report.impacted_nodes}
    assert "caller_a" in impacted_names
    assert "caller_b" in impacted_names
    # Cycle did not cause infinite loop or error


@pytest.mark.asyncio
async def test_mcp_code_tools_registration_and_execution(sample_codegraph_db: Path) -> None:
    server = create_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    # Verify 5 tools registered
    expected_tools = {
        "kb_code_search",
        "kb_code_node",
        "kb_code_callers",
        "kb_code_callees",
        "kb_code_impact",
    }
    assert expected_tools.issubset(tool_names)

    project_arg = str(sample_codegraph_db.parent.parent)

    # 1. Test kb_code_search
    res_search = await server.call_tool("kb_code_search", {"query": "payroll", "project_path": project_arg})
    assert not res_search.is_error
    assert "api_calculate_payroll" in res_search.content[0].text

    # 2. Test kb_code_node
    res_node = await server.call_tool(
        "kb_code_node", {"symbol": "calculate_net_pay", "project_path": project_arg}
    )
    assert not res_node.is_error
    assert "calculate_net_pay" in res_node.content[0].text
    assert "def calculate_net_pay" in res_node.content[0].text

    # 3. Test kb_code_callers
    res_callers = await server.call_tool(
        "kb_code_callers", {"symbol": "calculate_net_pay", "project_path": project_arg}
    )
    assert not res_callers.is_error
    assert "api_calculate_payroll" in res_callers.content[0].text

    # 4. Test kb_code_callees
    res_callees = await server.call_tool(
        "kb_code_callees", {"symbol": "calculate_net_pay", "project_path": project_arg}
    )
    assert not res_callees.is_error
    assert "compute_pit_tax" in res_callees.content[0].text

    # 5. Test kb_code_impact
    res_impact = await server.call_tool(
        "kb_code_impact", {"symbol": "compute_pit_tax", "depth": 2, "project_path": project_arg}
    )
    assert not res_impact.is_error
    assert "Blast Radius" in res_impact.content[0].text
    assert "src/payroll.py" in res_impact.content[0].text
    assert "src/api.py" in res_impact.content[0].text
