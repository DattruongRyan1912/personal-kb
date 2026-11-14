"""The two core SDD tools (issue 2.2): search the memory fabric, or read one spec whole."""

import hashlib
import re

from pydantic import BaseModel, Field

from personal_kb.services.chunking import parse_frontmatter
from personal_kb.services.retrieval import UNRANKED_WARNING
from personal_kb.tools.base import BaseAgentTool, ToolContext

# A query covering several points matches every chunk only in part: the re-ranker scores them all below its threshold
# and the search finds nothing (a 6-step scenario scored 0.28; each of its points alone 0.66-0.87).
MAX_QUERY_CHARS = 200
SPLIT_QUERY = (
    "Lỗi: câu truy vấn dài {n} ký tự và gồm nhiều ý nên không tra cứu chính xác được (tối đa {max} ký tự). "
    'Hãy tách thành từng ý và gọi lại với một câu ngắn cho mỗi ý, ví dụ "IPN VNPay gửi 2 lần"; khi đã biết mã spec, '
    "đọc nguyên văn bằng get_full_spec_content."
)


class SearchArgs(BaseModel):
    query: str = Field(
        min_length=1,
        description="Một ý cần tra, viết ngắn (dưới 15 từ). Câu hỏi nhiều ý thì tra từng ý, mỗi lần một câu ngắn",
    )


class SpecIdArgs(BaseModel):
    spec_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$", description="Mã tài liệu Spec, ví dụ SPC-2")


class SearchSddKnowledge(BaseAgentTool):
    name: str = "search_sdd_knowledge"
    description: str = (
        "Dùng công cụ này ĐẦU TIÊN khi người dùng hỏi về nghiệp vụ, logic hệ thống, quy trình hoặc cần tìm kiếm ID "
        "tài liệu Spec (SDD)."
    )
    args_schema: type[BaseModel] = SearchArgs
    status: str = "🔍 Đang tìm kiếm trong kho Spec: “{query}”..."

    async def run(self, args: SearchArgs, ctx: ToolContext) -> str:
        if len(args.query) > MAX_QUERY_CHARS:
            return SPLIT_QUERY.format(n=len(args.query), max=MAX_QUERY_CHARS)
        results = await ctx.retriever.search(args.query)
        if not results:
            return f"Không tìm thấy tài liệu SDD nào liên quan đến: {args.query}"
        titles = await _titles(ctx, {spec_id for r in results for spec_id in r.spec_ids})
        lines = [f"Kết quả tra cứu SDD cho: {args.query}"]
        if not all(r.reranked for r in results):
            lines.insert(0, UNRANKED_WARNING)
        for i, r in enumerate(results, 1):
            where = f" {' > '.join(r.headings)}" if r.headings else ""
            specs = ", ".join(f"{s} «{titles[s]}»" if titles.get(s) else s for s in r.spec_ids)
            lines.append(f"[{i}] ({specs}, {r.source}, {r.score:.2f}){where}\n{r.text}")
        return "\n\n".join(lines)


class VerifyCitationArgs(BaseModel):
    spec_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$", description="Mã tài liệu Spec, ví dụ HR-M05")
    quote: str = Field(min_length=3, description="Đoạn văn bản trích dẫn cần đối soát với tài liệu gốc")


class GetFullSpecContent(BaseAgentTool):
    name: str = "get_full_spec_content"
    description: str = (
        "Chỉ dùng khi ĐÃ BIẾT CHẮC CHẮN mã Spec ID (VD: SPC-123) và cần đọc nguyên văn 100% nội dung (Code, Table) của "
        "tài liệu đó để phân tích chuyên sâu."
    )
    args_schema: type[BaseModel] = SpecIdArgs
    status: str = "📄 Đang đọc tài liệu {spec_id}..."

    async def run(self, args: SpecIdArgs, ctx: ToolContext) -> str:
        doc = await ctx.documents.get(args.spec_id)
        if doc is None:
            return f"Không tìm thấy spec {args.spec_id} trong kho SDD."
        return f"{doc.spec_id} — {doc.title}\n\n{doc.content}"


def _normalize_ws(text: str) -> str:
    """Normalize repeated whitespace and lowercase for reliable matching."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _find_heading(content: str, quote: str) -> str:
    """Find the section heading immediately preceding the quote."""
    norm_content = _normalize_ws(content)
    norm_quote = _normalize_ws(quote)
    idx = norm_content.find(norm_quote)
    if idx == -1:
        return "N/A"
    headings = re.findall(r"^(#{1,6}\s+.+)$", content, re.MULTILINE)
    last_heading = "N/A"
    for h in headings:
        h_norm = _normalize_ws(h)
        h_pos = norm_content.find(h_norm)
        if 0 <= h_pos <= idx:
            last_heading = h.strip()
        elif h_pos > idx:
            break
    return last_heading


class VerifyCitation(BaseAgentTool):
    name: str = "verify_citation"
    description: str = (
        "Xác minh tính xác thực và nguồn gốc của một trích dẫn (quote/claim) đối chiếu với tài liệu Spec gốc. "
        "Kiểm tra xem nội dung trích dẫn có thực sự tồn tại trong tài liệu hay không, trích xuất heading chứa "
        "đoạn văn bản đó, trạng thái tài liệu và SHA-256 hash để bảo đảm không bị ảo giác (hallucination)."
    )
    args_schema: type[BaseModel] = VerifyCitationArgs
    status: str = "🔎 Đang đối soát đoạn trích với tài liệu {spec_id}..."

    async def run(self, args: VerifyCitationArgs, ctx: ToolContext) -> str:
        s_id = args.spec_id.strip()
        q = args.quote.strip()
        doc = await ctx.documents.get(s_id)
        if doc is None:
            return f"❌ THẤT BẠI: Tài liệu '{s_id}' không tồn tại trong kho SDD."

        meta, _ = parse_frontmatter(doc.content)
        status = meta.get("status") or "active"
        content_hash = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()

        matched = _normalize_ws(q) in _normalize_ws(doc.content)
        heading = _find_heading(doc.content, q) if matched else "N/A"

        if matched:
            return (
                f"✅ XÁC THỰC THÀNH CÔNG: Trích dẫn tồn tại trong {s_id} ({doc.title})\n"
                f"- Mục chứa trích dẫn: {heading}\n"
                f"- Trạng thái tài liệu: {status}\n"
                f"- Hash toàn vẹn (SHA-256): {content_hash[:16]}...\n"
                f"- Đoạn trích: {q}"
            )
        return (
            f"⚠️ CẢNH BÁO: Không tìm thấy đoạn trích trong tài liệu {s_id} ({doc.title}). "
            f"Hãy đọc lại tài liệu bằng get_full_spec_content hoặc tra cứu lại bằng search_sdd_knowledge."
        )


class NoArgs(BaseModel):
    pass


MAX_CATALOG = 200


class ListSddSpecs(BaseAgentTool):
    """The spec catalog. With five tool calls per question, a scenario across many flows cannot search each step and
    read each spec; listing the specs once lets the agent read the ones that matter."""

    name: str = "list_sdd_specs"
    description: str = (
        "Liệt kê mã, tên và người viết của mọi tài liệu Spec (SDD) trong kho, không kèm nội dung. Dùng khi câu hỏi "
        "là một kịch bản nhiều bước hoặc trải rộng nhiều luồng nghiệp vụ, để chọn các spec cần đọc nguyên văn bằng "
        "get_full_spec_content."
    )
    args_schema: type[BaseModel] = NoArgs
    status: str = "📚 Đang xem danh mục tài liệu Spec..."

    async def run(self, args: NoArgs, ctx: ToolContext) -> str:
        docs = await ctx.documents.all()
        if not docs:
            return "Kho SDD chưa có tài liệu nào."
        lines = [
            f"Danh mục tài liệu SDD ({len(docs)}). Đây chỉ là danh mục: muốn biết nội dung, đọc spec bằng "
            "get_full_spec_content."
        ]
        for doc in docs[:MAX_CATALOG]:
            owner = parse_frontmatter(doc.content)[0].get("owner")
            lines.append(f"- {doc.spec_id}: {doc.title or doc.spec_id}" + (f" (người viết: {owner})" if owner else ""))
        if len(docs) > MAX_CATALOG:
            lines.append(f"… và {len(docs) - MAX_CATALOG} spec khác: tra cứu bằng search_sdd_knowledge.")
        return "\n".join(lines)


class ProposeKbUpdateArgs(BaseModel):
    spec_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$", description="Mã tài liệu Spec, ví dụ HR-M04")
    title: str = Field(min_length=1, description="Tiêu đề tóm lược nội dung đề xuất cập nhật")
    section: str = Field(default="", description="Tên mục hoặc heading cần cập nhật trong tài liệu")
    proposed_content: str = Field(min_length=1, description="Nội dung Markdown mới đề xuất")
    rationale: str = Field(
        min_length=1, description="Lý do cập nhật (căn cứ, yêu cầu của người dùng, hoặc phát hiện mới)"
    )


class ProposeKbUpdate(BaseAgentTool):
    name: str = "propose_kb_update"
    description: str = (
        "Dùng khi phát hiện thông tin trong spec bị cũ, thiếu sót, hoặc người dùng cung cấp thông tin kỹ thuật "
        "mới/sửa đổi mâu thuẫn với spec hiện có. Công cụ này tạo một đề xuất (proposal) đưa vào hàng đợi phê duyệt "
        "cho con người xem xét. Tuyệt đối không tự ý khẳng định là đã cập nhật tài liệu gốc."
    )
    args_schema: type[BaseModel] = ProposeKbUpdateArgs
    status: str = "📝 Đang gửi đề xuất cập nhật cho tài liệu {spec_id}..."

    async def run(self, args: ProposeKbUpdateArgs, ctx: ToolContext) -> str:
        from personal_kb.services.proposals import ProposalStore

        store = ProposalStore()
        prop = store.create(
            spec_id=args.spec_id.strip(),
            title=args.title.strip(),
            section=args.section.strip(),
            proposed_content=args.proposed_content.strip(),
            rationale=args.rationale.strip(),
        )
        return (
            f"✅ ĐÃ TẠO ĐỀ XUẤT CẬP NHẬT TRI THỨC THÀNH CÔNG:\n"
            f"- Mã đề xuất: {prop.id}\n"
            f"- Tài liệu: {prop.spec_id}\n"
            f"- Tiêu đề: {prop.title}\n"
            f"- Mục: {prop.section or 'N/A'}\n"
            f"- Trạng thái: {prop.status} (Chờ con người phê duyệt tại trang Quản trị tri thức)\n"
            f"- Lý do: {prop.rationale}"
        )


async def _titles(ctx: ToolContext, spec_ids: set[str]) -> dict[str, str]:
    """Document titles for citations ("[Tên tài liệu](SPEC_ID)"); best effort: a missing title leaves the bare id."""
    if ctx.documents is None:
        return {}
    titles = {}
    for spec_id in sorted(spec_ids):
        try:
            doc = await ctx.documents.get(spec_id)
        except Exception:
            continue
        if doc and doc.title:
            titles[spec_id] = doc.title
    return titles


_FULL_SPEC_HEAD = re.compile(r"^([A-Za-z0-9_.-]{1,64}) — (.+)$", re.MULTILINE)
_SEARCH_SOURCES = re.compile(r"^\[\d+\] \((.+), (?:vector|graph), [0-9.]+\)", re.MULTILINE)
_SEARCH_SPEC = re.compile(r"([A-Za-z0-9_.-]{1,64})(?: «([^»]+)»)?")
_VERIFY_SUCCESS = re.compile(
    r"^✅ XÁC THỰC THÀNH CÔNG: Trích dẫn tồn tại trong ([A-Za-z0-9_.-]{1,64}) \((.+)\)", re.MULTILINE
)


def sources_in(tool_output: str) -> dict[str, str]:
    """{spec id: title} the output of either tool above names, read back from the text the tools wrote."""
    head = _FULL_SPEC_HEAD.match(tool_output)
    if head:
        return {head.group(1): head.group(2).strip()}
    v_match = _VERIFY_SUCCESS.match(tool_output)
    if v_match:
        return {v_match.group(1): v_match.group(2).strip()}
    sources: dict[str, str] = {}
    for listed in _SEARCH_SOURCES.findall(tool_output):
        for spec_id, title in _SEARCH_SPEC.findall(listed):
            sources.setdefault(spec_id, title or spec_id)
    return sources
