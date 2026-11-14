"""MCP tools for Code Intelligence and AST Knowledge Graph navigation.

Connects directly to repository CodeGraph index (.codegraph/codegraph.db),
allowing AI Agents to search symbols, trace callers/callees, and analyze
blast radius impact without leaving the Personal-KB MCP server.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from personal_kb.services.code_graph_indexer import CodeGraphIndexer
from personal_kb.services.code_graph_reader import CodeGraphReader

log = logging.getLogger(__name__)

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
)

WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    openWorldHint=False,
)


__all__ = ["register_code_tools"]


def _get_reader(project_path: str = "") -> CodeGraphReader:
    p = project_path.strip() if project_path else None
    return CodeGraphReader(p)


def register_code_tools(server: MCPServer) -> None:
    """Register CodeGraph tools onto the given MCP Server."""

    @server.tool(
        name="kb_code_status",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Kiểm tra trạng thái và telemetry của kho dữ liệu CodeGraph (.codegraph/codegraph.db): "
            "số lượng file, tổng số symbol nodes theo loại (class, function, method, struct...), "
            "tổng số quan hệ edges và dung lượng database."
        ),
    )
    async def kb_code_status(project_path: str = "") -> str:
        """Get CodeGraph status and telemetry metadata."""
        reader = _get_reader(project_path)
        status = reader.get_status()
        if not status.available:
            return (
                f"Chưa tìm thấy chỉ mục CodeGraph tại '{project_path or 'thư mục hiện tại'}'. "
                f"Hãy dùng tool 'kb_code_index' hoặc lệnh CLI 'personal-kb index-code' để tạo chỉ mục."
            )

        lines = [
            "### CodeGraph Telemetry Status:\n",
            f"- **Database:** `{status.db_path}`",
            f"- **Dung lượng:** {status.db_size_bytes / (1024 * 1024):.2f} MB",
            f"- **Tổng số File:** {status.file_count} files",
            f"- **Tổng số Symbol Nodes:** {status.node_count} nodes",
            f"- **Tổng số Edges:** {status.edge_count} edges\n",
        ]

        if status.nodes_by_kind:
            lines.append("#### Phân bố theo loại Node (Top kinds):")
            sorted_kinds = sorted(status.nodes_by_kind.items(), key=lambda x: x[1], reverse=True)
            for k, count in sorted_kinds[:10]:
                lines.append(f"- `{k}`: {count}")

        if status.files_by_language:
            lines.append("\n#### Phân bố theo ngôn ngữ (Files):")
            for lang, count in status.files_by_language.items():
                lines.append(f"- `{lang}`: {count} files")

        return "\n".join(lines)

    @server.tool(
        name="kb_code_index",
        annotations=WRITE_ANNOTATIONS,
        description=(
            "Quét và lập chỉ mục cú pháp AST (Native Tree-sitter Ingestion & Two-Pass Linker) "
            "cho dự án, lưu vào SQLite .codegraph/codegraph.db. "
            "Hỗ trợ Python, TypeScript/JS, Swift, Dart, C#, Go, Rust, Java mà không tốn LLM token. "
            "Có cơ chế incremental hashing (SHA-256) chỉ quét file mới/thay đổi."
        ),
    )
    async def kb_code_index(
        project_path: str = "",
        force: bool = False,
    ) -> str:
        """Index a project's codebase using native Tree-sitter AST extraction."""
        target_str = project_path.strip() or str(Path.cwd())  # noqa: ASYNC240
        target = Path(target_str).expanduser().resolve()  # noqa: ASYNC240
        if not target.is_dir():
            return f"Lỗi: Thư mục dự án '{target}' không tồn tại."

        try:
            indexer = CodeGraphIndexer(target)
            res = await asyncio.to_thread(indexer.index, force=force)
            lines = [
                f"### Quét và Lập Chỉ Mục CodeGraph Thành Công cho `{target.name}`:\n",
                f"- **DB Path:** `{res.db_path}` ({res.db_size_bytes / (1024 * 1024):.2f} MB)",
                f"- **Thời gian thực thi:** {res.duration_seconds:.2f}s",
                (
                    f"- **Tập tin đã index:** {res.files_indexed} files "
                    f"(Bỏ qua: {res.files_skipped}, Xóa: {res.files_deleted})"
                ),
                f"- **Tổng số Symbol Nodes:** {res.nodes_count} nodes",
                f"- **Tổng số Quan Hệ Edges:** {res.edges_count} edges",
            ]
            if res.errors:
                lines.append(f"- **Cảnh báo lỗi ({len(res.errors)}):**")
                for err in res.errors[:3]:
                    lines.append(f"  - `{err}`")
            return "\n".join(lines)
        except Exception as e:
            log.exception("kb_code_index failed: %s", e)
            return f"Lỗi khi lập chỉ mục codebase: {e}"

    @server.tool(
        name="kb_code_search",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Tìm kiếm các biểu tượng mã nguồn (function, class, method, struct, interface...) "
            "trong codebase qua chỉ mục CodeGraph. "
            "Hỗ trợ lọc theo 'kind' ('function', 'class', 'method', 'interface', 'struct', 'type_alias') "
            "và 'language' ('python', 'typescript', 'go', 'dart', 'csharp')."
        ),
    )
    async def kb_code_search(
        query: str,
        kind: str = "",
        language: str = "",
        limit: int = 15,
        project_path: str = "",
    ) -> str:
        """Search code symbols in the project's CodeGraph index."""
        reader = _get_reader(project_path)
        if not reader.is_available:
            return (
                f"Chưa tìm thấy chỉ mục CodeGraph (.codegraph/codegraph.db) "
                f"tại '{project_path or 'thư mục hiện tại'}'. "
                f"Hãy chạy 'codegraph init' tại thư mục gốc của repository để tạo chỉ mục."
            )

        q = query.strip()
        if not q:
            return "Lỗi: Tham số 'query' không được để trống."

        results = reader.search_symbols(
            query=q,
            kind=kind.strip() or None,
            language=language.strip() or None,
            limit=limit,
        )

        if not results:
            return f"Không tìm thấy symbol nào khớp với từ khóa '{q}'."

        lines = [f"### Kết quả tìm kiếm Code Symbols cho '{q}' ({len(results)} kết quả):\n"]
        for node in results:
            sig = f" — `{node.signature}`" if node.signature else ""
            lines.append(
                f"- **{node.name}** (`{node.kind}`) in `{node.file_path}:{node.start_line}-{node.end_line}`{sig}"
            )
            if node.docstring:
                doc_preview = node.docstring.strip().split("\n")[0][:100]
                lines.append(f"  *Doc:* {doc_preview}")
        return "\n".join(lines)

    @server.tool(
        name="kb_code_node",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Xem chi tiết một symbol trong mã nguồn: vị trí file, toạ độ dòng (start_line, end_line), "
            "signature, docstring, đoạn mã nguồn thực tế và số lượng callers/callees liên kết."
        ),
    )
    async def kb_code_node(
        symbol: str,
        file: str = "",
        include_code: bool = True,
        project_path: str = "",
    ) -> str:
        """Inspect a specific code symbol node and optionally view its source code slice."""
        reader = _get_reader(project_path)
        if not reader.is_available:
            return (
                "Chưa tìm thấy chỉ mục CodeGraph (.codegraph/codegraph.db). "
                "Hãy chạy 'codegraph init' tại thư mục gốc repository."
            )

        sym = symbol.strip()
        if not sym:
            return "Lỗi: Tham số 'symbol' không được để trống."

        node = reader.get_node(sym, file_path=file.strip() or None)
        if not node:
            return f"Không tìm thấy symbol '{sym}'" + (f" trong file '{file}'." if file else ".")

        callers = reader.get_callers(node.id, limit=5)
        callees = reader.get_callees(node.id, limit=5)

        out = [
            f"### Code Symbol: `{node.name}` ({node.kind})\n",
            f"- **Qualified Name:** `{node.qualified_name}`",
            f"- **Location:** `{node.file_path}:{node.start_line}-{node.end_line}` (Lang: `{node.language}`)",
        ]
        if node.signature:
            out.append(f"- **Signature:** `{node.signature}`")
        if node.return_type:
            out.append(f"- **Return Type:** `{node.return_type}`")
        if node.docstring:
            out.append(f"- **Docstring:**\n```\n{node.docstring.strip()}\n```")

        out.append(f"- **Direct Callers Count:** {len(callers)} caller(s)")
        out.append(f"- **Direct Callees Count:** {len(callees)} callee(s)")

        if include_code:
            code = reader.read_code_snippet(node)
            if code:
                out.append(f"\n**Source Code ({node.file_path}:{node.start_line}-{node.end_line}):**")
                out.append(f"```{node.language}\n{code}\n```")

        return "\n".join(out)

    @server.tool(
        name="kb_code_callers",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Tìm tất cả các hàm/method/symbol gọi đến symbol mục tiêu (Incoming Calls). "
            "Rất hữu ích khi cần đổi tên hàm, refactor hoặc kiểm tra xem hàm có đang được sử dụng ở đâu."
        ),
    )
    async def kb_code_callers(
        symbol: str,
        file: str = "",
        limit: int = 20,
        project_path: str = "",
    ) -> str:
        """Find all functions/methods that call the specified symbol."""
        reader = _get_reader(project_path)
        if not reader.is_available:
            return (
                "Chưa tìm thấy chỉ mục CodeGraph (.codegraph/codegraph.db). "
                "Hãy chạy 'codegraph init' tại thư mục gốc repository."
            )

        sym = symbol.strip()
        if not sym:
            return "Lỗi: Tham số 'symbol' không được để trống."

        callers = reader.get_callers(sym, file_path=file.strip() or None, limit=limit)
        if not callers:
            return f"Không tìm thấy lời gọi (caller) nào đến symbol '{sym}'."

        lines = [f"### Danh sách Callers gọi đến `{sym}` ({len(callers)} callers):\n"]
        for rel in callers:
            caller = rel.node
            edge = rel.edge
            at_line = f" (line {edge.line})" if edge.line else ""
            lines.append(f"- **{caller.name}** (`{caller.kind}`) — `{caller.file_path}:{caller.start_line}`{at_line}")
        return "\n".join(lines)

    @server.tool(
        name="kb_code_callees",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Tìm tất cả các hàm/method/symbol mà symbol mục tiêu gọi tới (Outgoing Calls). "
            "Rất hữu ích khi cần phân tích luồng thực thi bên trong một hàm hoặc module."
        ),
    )
    async def kb_code_callees(
        symbol: str,
        file: str = "",
        limit: int = 20,
        project_path: str = "",
    ) -> str:
        """Find all functions/methods that the specified symbol calls."""
        reader = _get_reader(project_path)
        if not reader.is_available:
            return (
                "Chưa tìm thấy chỉ mục CodeGraph (.codegraph/codegraph.db). "
                "Hãy chạy 'codegraph init' tại thư mục gốc repository."
            )

        sym = symbol.strip()
        if not sym:
            return "Lỗi: Tham số 'symbol' không được để trống."

        callees = reader.get_callees(sym, file_path=file.strip() or None, limit=limit)
        if not callees:
            return f"Symbol '{sym}' không gọi hàm/symbol con nào được ghi nhận trong chỉ mục."

        lines = [f"### Danh sách Callees được `{sym}` gọi ({len(callees)} callees):\n"]
        for rel in callees:
            callee = rel.node
            edge = rel.edge
            at_line = f" (call at line {edge.line})" if edge.line else ""
            lines.append(f"- **{callee.name}** (`{callee.kind}`) — `{callee.file_path}:{callee.start_line}`{at_line}")
        return "\n".join(lines)

    @server.tool(
        name="kb_code_impact",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Phân tích tác động lan truyền (Transitive Blast Radius) khi thay đổi một symbol. "
            "Duyệt đồ thị ngược (backward BFS) theo các tầng lời gọi hàm (depth=1..5) "
            "để tổng hợp danh sách toàn bộ các symbol và file bị ảnh hưởng."
        ),
    )
    async def kb_code_impact(
        symbol: str,
        file: str = "",
        depth: int = 2,
        project_path: str = "",
    ) -> str:
        """Analyze transitive blast radius of modifying a code symbol."""
        reader = _get_reader(project_path)
        if not reader.is_available:
            return (
                "Chưa tìm thấy chỉ mục CodeGraph (.codegraph/codegraph.db). "
                "Hãy chạy 'codegraph init' tại thư mục gốc repository."
            )

        sym = symbol.strip()
        if not sym:
            return "Lỗi: Tham số 'symbol' không được để trống."

        report = reader.get_impact(sym, file_path=file.strip() or None, max_depth=depth)
        if not report.focal_nodes:
            return f"Không tìm thấy symbol '{sym}' để phân tích tác động."

        focal = report.focal_nodes[0]
        if not report.impacted_nodes:
            return (
                f"### Phân tích Tác động (Blast Radius) cho `{focal.name}` (Depth: {depth}):\n\n"
                f"Symbol `{focal.name}` (`{focal.file_path}:{focal.start_line}`) là lá (leaf) "
                f"hoặc chưa có hàm nào trong codebase gọi tới. "
                f"Tác động lan truyền trực tiếp: 0 symbol."
            )

        lines = [
            f"### Phân tích Tác động (Blast Radius) khi sửa `{focal.name}` (Depth: {depth}):\n",
            f"- **Focal Symbol:** `{focal.qualified_name}` (`{focal.file_path}:{focal.start_line}`)",
            f"- **Tổng số Symbol bị ảnh hưởng:** {len(report.impacted_nodes)} symbols",
            f"- **Tổng số File bị ảnh hưởng:** {len(report.by_file)} files\n",
            "#### Chi tiết theo từng File:",
        ]

        for file_path, nodes in report.by_file.items():
            lines.append(f"\n📂 **`{file_path}`** ({len(nodes)} symbols):")
            for n in nodes:
                lines.append(f"  - `{n.name}` (`{n.kind}`, Line {n.start_line})")

        return "\n".join(lines)
