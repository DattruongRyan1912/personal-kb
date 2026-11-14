"""MCP tools that read the specs: search, cite, read whole, list, and the spec:// resource."""

import hashlib
import json
import logging
import re

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from personal_kb.mcp.context import context_holder
from personal_kb.services.chunking import parse_frontmatter
from personal_kb.services.projects import project_of
from personal_kb.services.retrieval import UNRANKED_WARNING

log = logging.getLogger(__name__)

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
)


def _normalize_ws(text: str) -> str:
    """Normalize whitespace and lowercase for reliable fuzzy/whitespace-tolerant quote matching."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _find_heading(content: str, quote: str) -> str:
    """Find the nearest markdown heading above the quote occurrence."""
    norm_content = _normalize_ws(content)
    norm_quote = _normalize_ws(quote)
    idx = norm_content.find(norm_quote)
    if idx == -1:
        return "N/A"
    # Search backwards in raw content for the nearest header line (# ...)
    lines = content.splitlines()
    curr_heading = "Top of Document"
    running_len = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            curr_heading = stripped.lstrip("#").strip()
        running_len += len(_normalize_ws(line)) + 1
        if running_len >= idx:
            break
    return curr_heading


def register_spec_tools(server: MCPServer) -> None:
    @server.tool(
        name="search_knowledge",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Tìm kiếm ngữ nghĩa và quan hệ trong kho tri thức tài liệu đặc tả nghiệp vụ (Personal-KB). "
            "Trả về các đoạn trích có điểm tương đồng cao nhất kèm tiêu đề mục và mã Spec ID. "
            "Có thể chỉ định 'project' để thu hẹp phạm vi tìm kiếm (ví dụ: 'Demo-Core', 'MyNotch', 'AGY-Remote-Hub', "
            "'Personal-KB')."
        ),
    )
    async def search_knowledge(query: str, limit: int = 5, project: str = "") -> str:
        """Search knowledge base with hybrid retrieval."""
        ctx = context_holder.get()
        if not query or not query.strip():
            return "Lỗi: Query không được để trống."

        proj_filter = project.strip() if project and project.strip() and project.strip().upper() != "ALL" else None
        try:
            results = await ctx.retriever.search(query.strip(), project_id=proj_filter)
        except TypeError:
            results = await ctx.retriever.search(query.strip())
        if not results:
            proj_info = f" trong dự án '{project}'" if proj_filter else ""
            return f"Không tìm thấy tài liệu nào liên quan đến: '{query}'{proj_info}"

        # Limit results if requested
        active_results = results[:limit]
        spec_ids = {spec_id for r in active_results for spec_id in r.spec_ids}
        titles: dict[str, str] = {}
        if ctx.documents:
            for s_id in sorted(spec_ids):
                try:
                    doc = await ctx.documents.get(s_id)
                    if doc and doc.title:
                        titles[s_id] = doc.title
                except Exception:
                    continue

        # Base frontend URL for clickable links
        frontend_url = "http://localhost:3000"
        if hasattr(ctx, "settings") and ctx.settings and getattr(ctx.settings, "frontend_base_url", None):
            frontend_url = ctx.settings.frontend_base_url.rstrip("/")

        lines = [f"Kết quả tra cứu cho query: '{query}' ({len(active_results)} kết quả):"]
        if not all(r.reranked for r in active_results):
            lines.insert(0, UNRANKED_WARNING)
        for i, r in enumerate(active_results, 1):
            where = f" > {' > '.join(r.headings)}" if r.headings else ""
            spec_names = ", ".join(f"{s} («{titles[s]}»)" if titles.get(s) else s for s in r.spec_ids)
            deep_links = ", ".join(f"{frontend_url}/specs/{s}" for s in r.spec_ids)
            resources = ", ".join(f"spec://{s}" for s in r.spec_ids)
            lines.append(
                f"[{i}] [{spec_names} | Nguồn: {r.source} | Điểm: {r.score:.2f}]{where}\n"
                f"Trích dẫn: {r.text}\n"
                f"🔗 Link xem nguồn: {deep_links} | 📦 Resource: {resources}"
            )

        return "\n\n".join(lines)

    @server.tool(
        name="verify_citation",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Xác minh tính xác thực và nguồn gốc của một trích dẫn (quote/claim) đối chiếu với tài liệu Spec gốc. "
            "Kiểm tra xem nội dung trích dẫn có thực sự tồn tại trong tài liệu hay không, trích xuất heading chứa "
            "đoạn văn bản đó, trạng thái tài liệu và SHA-256 hash để làm bằng chứng kiểm toán (Audit Trail)."
        ),
    )
    async def verify_citation(spec_id: str, quote: str) -> str:
        """Verify citation snippet against the authoritative spec document."""
        ctx = context_holder.get()
        s_id = spec_id.strip()
        q = quote.strip()
        if not s_id or not q:
            return "Lỗi: spec_id và quote không được để trống."

        doc = await ctx.documents.get(s_id)
        if doc is None:
            return f"❌ THẤT BẠI: Tài liệu '{s_id}' không tồn tại trong kho tri thức."

        meta, _ = parse_frontmatter(doc.content)
        status = meta.get("status") or "active"
        owner = meta.get("owner") or meta.get("author") or "N/A"
        content_hash = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()

        matched = _normalize_ws(q) in _normalize_ws(doc.content)
        heading = _find_heading(doc.content, q) if matched else "N/A"

        frontend_url = "http://localhost:3000"
        if hasattr(ctx, "settings") and ctx.settings and getattr(ctx.settings, "frontend_base_url", None):
            frontend_url = ctx.settings.frontend_base_url.rstrip("/")
        view_url = f"{frontend_url}/specs/{s_id}"

        result = {
            "verified": matched,
            "spec_id": s_id,
            "title": doc.title or s_id,
            "status": status,
            "owner": owner,
            "section_heading": heading,
            "content_hash": content_hash,
            "view_url": view_url,
            "resource_uri": f"spec://{s_id}",
        }

        if matched:
            verdict = (
                f"✅ XÁC THỰC THÀNH CÔNG [HỢP LỆ]\n"
                f"- Tài liệu: {s_id} — {doc.title} (Trạng thái: {status})\n"
                f"- Mục chứa trích dẫn: {heading}\n"
                f"- Hash toàn vẹn (SHA-256): {content_hash[:16]}...\n"
                f"- Link xem trực tiếp: {view_url}\n"
                f"- Resource: spec://{s_id}"
            )
        else:
            verdict = (
                f"⚠️ CẢNH BÁO: Trích dẫn không tìm thấy trong tài liệu {s_id}!\n"
                f"- Tài liệu tồn tại: Có ({doc.title})\n"
                f"- Nội dung đối soát: Không tìm thấy đoạn trích '{q}' trong văn bản gốc.\n"
                f"- Link đối chiếu: {view_url}"
            )

        return verdict + "\n\n" + json.dumps(result, ensure_ascii=False, indent=2)

    @server.tool(
        name="get_spec_content",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Đọc nguyên văn toàn bộ 100% nội dung (bảng biểu, quy tắc, code) của một tài liệu "
            "Spec Markdown theo spec_id (Ví dụ: HR-M01, HR-M02, SPC-1)."
        ),
    )
    async def get_spec_content(spec_id: str) -> str:
        """Get full spec markdown content."""
        ctx = context_holder.get()
        s_id = spec_id.strip()
        if not s_id:
            return "Lỗi: spec_id không được để trống."

        doc = await ctx.documents.get(s_id)
        if doc is None:
            return f"Không tìm thấy tài liệu {s_id} trong kho tri thức."

        return f"# {doc.spec_id} — {doc.title}\n\n{doc.content}"

    @server.tool(
        name="list_specs",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Liệt kê danh mục tất cả các tài liệu đặc tả (Spec) hiện có trong kho tri thức kèm mã ID, tiêu đề, "
            "dự án, tác giả/owner và trạng thái. Có thể lọc theo tham số 'project' (ví dụ: 'Demo-Core', 'MyNotch', "
            "'AGY-Remote-Hub', 'Personal-KB')."
        ),
    )
    async def list_specs(project: str = "") -> str:
        """List all available specs in the knowledge base."""
        ctx = context_holder.get()
        docs = await ctx.documents.all()
        if not docs:
            return "Kho tri thức hiện chưa có tài liệu nào."

        proj_filter = project.strip() if project and project.strip() and project.strip().upper() != "ALL" else None
        lines = [f"Danh mục tài liệu trong kho tri thức ({len(docs)} tài liệu):"]
        for doc in docs:
            meta, _ = parse_frontmatter(doc.content)
            owner = meta.get("owner") or meta.get("author") or "N/A"
            status = meta.get("status") or "active"
            # the project ingestion stored (frontmatter, folder or prefix: services/projects.py)
            doc_proj = getattr(doc, "project_id", "") or project_of(doc.spec_id, meta)

            if proj_filter and doc_proj.lower() != proj_filter.lower():
                continue

            lines.append(
                f"- **{doc.spec_id}** [Dự án: {doc_proj}]: {doc.title or doc.spec_id} (Tác giả: {owner} | Trạng "
                f"thái: {status})"
            )

        return "\n".join(lines)

    @server.resource(
        "spec://{spec_id}",
        mime_type="text/markdown",
        description="Đọc trực tiếp nội dung nguyên văn tài liệu spec qua URI scheme spec://{spec_id}",
    )
    async def read_spec_resource(spec_id: str) -> str:
        """Resource handler for spec://{spec_id}."""
        ctx = context_holder.get()
        doc = await ctx.documents.get(spec_id)
        if doc is None:
            raise ValueError(f"Tài liệu {spec_id} không tồn tại.")
        return doc.content
