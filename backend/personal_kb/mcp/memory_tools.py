"""MCP tools for the reflective and procedural memory: guardrails, golden exemplars, the cognitive router."""

import logging
import re

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from personal_kb.mcp.context import context_holder
from personal_kb.services.chunking import parse_frontmatter

log = logging.getLogger(__name__)

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
)


def is_constraint_header(s: str) -> bool:
    """Identify if a line denotes a negative constraint or gotcha header."""
    s = s.strip()
    if s.startswith(("- **[FORBIDDEN]", "- **[CAUTION]", "- **[MANDATORY]", "- **[INVARIANT]")):
        return True
    if re.match(r"^-\s+\*\*\[?(?:NC-[A-Z]+-\d+|G-[A-Z]+-\d+|GOTCHA-[A-Z]+-\d+)", s, re.IGNORECASE):
        return True
    if re.match(r"^###\s+.*\[?(?:NC-[A-Z]+-\d+|G-[A-Z]+-\d+|GOTCHA-[A-Z]+-\d+)", s, re.IGNORECASE):
        return True
    if re.match(r"^###\s+\[?(?:FORBIDDEN|CAUTION|MANDATORY|INVARIANT)\]?", s, re.IGNORECASE):
        return True
    if re.match(r"^###\s+Cạm bẫy", s, re.IGNORECASE):
        return True
    return False


def register_memory_tools(server: MCPServer) -> None:
    @server.tool(
        name="recall_guardrails",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Truy xuất các Ràng buộc phủ định (Negative Constraints) và Cạm bẫy kiến trúc (Gotchas) "
            "bắt buộc phải tuân thủ cho một dự án cụ thể ('Demo-Core', 'Personal-KB', 'MyNotch'). "
            "Dùng TRƯỚC KHI sinh mã nguồn, viết hàm tính toán, hoặc thiết kế schema/API. "
            "Có thể chỉ định 'topic' (ví dụ: 'payroll', 'timesheet', 'leave', 'employee', 'general') "
            "để thu hẹp phạm vi. Luôn áp dụng luật Top-3 Hard Limit để bảo vệ Context Window."
        ),
    )
    async def recall_guardrails(project: str, topic: str = "", limit: int = 3) -> str:
        """Recall top negative constraints and architectural guardrails for a project."""
        ctx = context_holder.get()
        p = project.strip().upper()
        if not p:
            return "Lỗi: Tham số 'project' không được để trống (ví dụ: 'Demo-Core', 'Personal-KB')."

        # Determine target spec_id for guardrails
        target_spec_id = (
            "HR-GOTCHAS"
            if ("HR" in p or "HRM" in p)
            else "PKB-GOTCHAS"
            if ("PKB" in p or "PERSONAL" in p)
            else "MYNOTCH-GOTCHAS"
            if ("MYNOTCH" in p or "NOTCH" in p)
            else "AGY-GOTCHAS"
            if ("AGY" in p or "REMOTE" in p or "HUB" in p)
            else "CYBEROS-GOTCHAS"
            if ("CYBER" in p)
            else "TOEIC-GOTCHAS"
            if ("TOEIC" in p)
            else None
        )

        if not target_spec_id and ctx.documents:
            all_docs = await ctx.documents.all()
            for doc in all_docs:
                if "GOTCHA" in doc.spec_id.upper() or "GUARDRAIL" in doc.spec_id.upper():
                    meta, _ = parse_frontmatter(doc.content)
                    doc_proj = (meta.get("project") or meta.get("project_id") or "").upper()
                    if p in doc_proj or doc_proj in p:
                        target_spec_id = doc.spec_id
                        break

        if not target_spec_id:
            return f"Hiện tại chưa có tài liệu Guardrails/Gotchas được cấu hình cho dự án '{project}'."

        doc = await ctx.documents.get(target_spec_id)
        if not doc:
            return f"Không tìm thấy tài liệu guardrails '{target_spec_id}' trong kho tri thức."

        # Parse constraints from doc.content
        lines = doc.content.splitlines()
        constraints: list[dict[str, any]] = []
        current_section = "General"
        current_item: dict[str, any] | None = None

        for line in lines:
            stripped = line.strip()
            if is_constraint_header(stripped):
                if current_item:
                    constraints.append(current_item)
                current_item = {
                    "section": current_section,
                    "header": stripped,
                    "body": [],
                }
            elif stripped.startswith("## "):
                current_section = stripped.lstrip("#").strip()
            elif current_item:
                if stripped.startswith("- "):
                    current_item["body"].append(stripped)
                elif not stripped.startswith("#") and stripped:
                    current_item["body"].append(stripped)
                elif stripped.startswith("#### "):
                    current_item["body"].append(stripped)

        if current_item:
            constraints.append(current_item)

        # Filter by topic if provided
        t = topic.strip().lower()
        topic_map = {
            "payroll": ["lương", "m04", "payroll", "thuế", "bảo hiểm", "decimal", "float", "nc-hr-04", "nc-hr-001"],
            "timesheet": ["chấm công", "m02", "timesheet", "ca đêm", "khóa sổ", "locked", "nc-hr-02"],
            "leave": ["phép", "m03", "leave", "nghỉ", "đơn", "nc-hr-03"],
            "employee": ["nhân sự", "hồ sơ", "m01", "hợp đồng", "delete", "soft delete", "nc-hr-01"],
            "general": ["chung", "cross-cutting", "sql", "float", "timezone", "nc-hr-00"],
            "battery": ["pin", "battery", "smc", "sailing", "chie", "xả", "charge", "discharge", "adapter"],
            "cleaner": ["cleaner", "gỡ cài đặt", "uninstall", "tcc", "trash", "thùng rác"],
            "selection": ["selection", "bôi đen", "chip", "panel", "popup"],
        }

        scored_constraints: list[tuple[int, dict[str, any]]] = []
        if t:
            match_keywords = topic_map.get(t, [t])
            for c in constraints:
                score = 0
                sec_lower = c["section"].lower()
                hdr_lower = c["header"].lower()
                body_lower = " ".join(c["body"]).lower()

                for kw in match_keywords:
                    if kw in sec_lower:
                        score += 15
                    if kw in hdr_lower:
                        score += 10
                    if kw in body_lower:
                        score += 2

                if score > 0:
                    scored_constraints.append((score, c))

            scored_constraints.sort(key=lambda x: x[0], reverse=True)
            filtered = [c for _, c in scored_constraints]
        else:
            filtered = constraints

        if not filtered and t:
            filtered = constraints

        # Apply hard limit (Top-3 per ADR-003)
        max_items = max(1, min(limit, 3))
        selected = filtered[:max_items]

        out = [
            "🛡️ [REFLECTIVE MEMORY] ACTIVE GUARDRAILS & NEGATIVE CONSTRAINTS",
            f"Dự án: {project} | Nguồn: {target_spec_id} | Chủ đề: {topic or 'Toàn dự án'}",
            f"Số lượng áp dụng: {len(selected)} (Áp dụng luật Top-3 Hard Limit để bảo vệ Context Window)\n",
        ]

        for idx, item in enumerate(selected, 1):
            out.append(f"[{idx}] {item['header']}")
            for b in item["body"]:
                out.append(f"    {b}")
            out.append("")

        out.append("⚠️ BẮT BUỘC: Mọi mã nguồn hoặc thiết kế phải tuân thủ 100% các điều cấm trên. Không vi phạm.")
        return "\n".join(out)

    @server.tool(
        name="recall_exemplar",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Truy xuất Mã nguồn Mẫu Chuẩn mực (Golden Few-Shot Exemplar) phục vụ sinh code và triển khai. "
            "Dùng khi Agent cần viết code (tính lương, chấm công, viết MCP tool, v.v.) để tham chiếu "
            "mã nguồn mẫu chuẩn sản xuất (Production-Grade Code) thay vì tự suy đoán. "
            "Tham số: 'project' (ví dụ: 'Demo-Core', 'Personal-KB') và 'pattern' (ví dụ: 'payroll', 'timesheet', 'mcp')."
        ),
    )
    async def recall_exemplar(project: str, pattern: str = "") -> str:
        """Retrieve production-grade code exemplars for implementation guidance."""
        ctx = context_holder.get()
        p = project.strip().upper()
        if not p:
            return "Lỗi: Tham số 'project' không được để trống (ví dụ: 'Demo-Core', 'Personal-KB')."

        target_spec_id = None
        pat = pattern.strip().lower()

        # Pattern mapping for Demo-Core
        if "HR" in p or "HRM" in p:
            if any(k in pat for k in ["payroll", "lương", "salary", "pit", "tax", "ex-001"]):
                target_spec_id = "HR-EX-001"
            elif any(k in pat for k in ["timesheet", "chấm công", "locked", "adjustment", "ca kíp", "ex-002"]):
                target_spec_id = "HR-EX-002"
            else:
                target_spec_id = "HR-EX-001"  # Default exemplar for HRM

        # Pattern mapping for Personal-KB
        elif "PERSONAL" in p or "PKB" in p:
            if any(k in pat for k in ["mcp", "tool", "server", "ex-001"]):
                target_spec_id = "PKB-EX-001"
            else:
                target_spec_id = "PKB-EX-001"

        if not target_spec_id and ctx.documents:
            all_docs = await ctx.documents.all()
            for doc in all_docs:
                if "EX-" in doc.spec_id.upper() or "EXEMPLAR" in doc.spec_id.upper():
                    meta, _ = parse_frontmatter(doc.content)
                    doc_proj = (meta.get("project") or meta.get("project_id") or "").upper()
                    if p in doc_proj or doc_proj in p:
                        target_spec_id = doc.spec_id
                        break

        if not target_spec_id:
            return f"Không tìm thấy Golden Exemplar nào cho dự án '{project}' với pattern '{pattern}'."

        doc = await ctx.documents.get(target_spec_id)
        if not doc:
            return f"Tài liệu Exemplar '{target_spec_id}' không tồn tại trong kho tri thức."

        meta, body = parse_frontmatter(doc.content)
        language = meta.get("language") or "python"

        # Extract code block if present
        code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", body, re.DOTALL)
        code_content = code_match.group(1).strip() if code_match else body.strip()

        # Format clean, high-signal response
        lines = [
            f"📦 [GOLDEN EXEMPLAR] MÃ NGUỒN MẪU CHUẨN MỰC: {doc.title or target_spec_id}",
            f"- Mã tài liệu: {target_spec_id} | Dự án: {meta.get('project', project)} | Ngôn ngữ: {language}",
            "- Tầng trí nhớ: Procedural Memory (Production Pattern)",
            "",
            f"```{language}",
            code_content,
            "```",
            "",
            "💡 HƯỚNG DẪN DÀNH CHO AGENT:",
            "- Hãy đối chiếu logic, cấu trúc type hints và các ràng buộc phủ định trong đoạn code mẫu trên.",
            "- Áp dụng trực tiếp vào giải pháp của bạn; không tự ý hạ cấp sang kiểu dữ liệu kém an toàn (như float).",
        ]
        return "\n".join(lines)

    @server.tool(
        name="query_cognitive_memory",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Công cụ Hợp nhất Nhận thức (Active Cognitive Memory Fabric). Tự động phân luồng (Two-Phase Intent-Gated "
            "Router): "
            "- Nếu viết code/triển khai: Đóng gói Context Triad (Spec Contract + Top-3 Negative Constraints + Golden "
            "Exemplar). "
            "- Nếu kiến trúc/hệ thống: Nạp các quyết định kiến trúc (Episodic ADRs). "
            "- Nếu tra cứu lý thuyết: Nạp các đoạn trích Spec kèm trích dẫn chính xác. "
            "Tham số: 'query' (câu hỏi/yêu cầu), 'project' ('Demo-Core', 'Personal-KB') và 'intent_hint' ('auto', "
            "'code', 'architecture', 'theory')."
        ),
    )
    async def query_cognitive_memory(query: str, project: str = "Demo-Core", intent_hint: str = "auto") -> str:
        """Route query and return multi-tier cognitive memory bundle."""
        from personal_kb.services.cognitive_router import CognitiveRouter

        ctx = context_holder.get()
        if not query or not query.strip():
            return "Lỗi: query không được để trống."

        router = CognitiveRouter(ctx)
        bundle = await router.route_and_retrieve(
            query.strip(), project=project.strip(), intent_hint=intent_hint.strip()
        )
        return bundle.formatted_context
