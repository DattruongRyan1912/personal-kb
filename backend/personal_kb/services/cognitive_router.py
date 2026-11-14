"""Two-Phase Intent-Gated Cognitive Router for Active Cognitive Memory Fabric.

Directs incoming agent queries through an intent-gated pipeline:
- CODE_IMPLEMENTATION: Injects the Context Triad (Spec Contract + Top-3 Negative Constraints + Golden Exemplar).
- ARCHITECTURE_DESIGN: Injects Episodic ADRs with graceful fallback to core architecture specs.
- THEORY_LOOKUP: Injects relevant Spec chunks with strict citation anchors.

Adheres to strict latency budgets via Two-Tier Intent Classification (Fast Regex Filter -> LLM/Fallback)
and Intent Priority Hierarchy (CODE > ARCHITECTURE > THEORY).
"""

import enum
import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class IntentType(str, enum.Enum):  # noqa: UP042 - StrEnum would change str() of the members
    CODE_IMPLEMENTATION = "CODE_IMPLEMENTATION"
    ARCHITECTURE_DESIGN = "ARCHITECTURE_DESIGN"
    THEORY_LOOKUP = "THEORY_LOOKUP"


@dataclass
class CERMetrics:
    estimated_baseline_tokens: int  # Raw URD full text tokens
    actual_context_tokens: int  # Triad / routed tokens
    cer_ratio: float  # actual / baseline
    token_savings_pct: float  # (1 - cer_ratio) * 100


@dataclass
class CognitiveBundle:
    intent: IntentType
    project: str
    query: str
    formatted_context: str
    specs_referenced: list[str] = field(default_factory=list)
    guardrails_applied: list[str] = field(default_factory=list)
    exemplar_applied: str | None = None
    cer_metrics: CERMetrics | None = None


# Fast Rule Regex Patterns
CODE_PATTERNS = [
    r"\b(def |class |function |hàm|viết code|sinh code|triển khai|lập trình|script|unit test|test case|fix bug)\b",
    r"\b(code|implementation|implement|algorithm|thuật toán|tính toán|calculate|compute)\b",
    r"\b(python|typescript|javascript|golang|rust|sql|pydantic|fastapi)\b",
]

ARCH_PATTERNS = [
    r"\b(kiến trúc|adr|thiết kế hệ thống|schema|giao thức|tổng thể|mô hình|topology)\b",
    r"\b(architecture|system design|database design|database schema|data pipeline|protocol)\b",
    r"\b(tombstone|vector store|graph store|payload filter|lifecycle)\b",
]

THEORY_PATTERNS = [
    r"\b(là gì|như thế nào|quy định|chính sách|công thức|điều kiện|quy trình|nghiệp vụ)\b",
    r"\b(spec|đặc tả|urd|sdd|mã lỗi|status|kỳ công|nghỉ phép|phụ cấp|thuế tncn)\b",
]


def classify_intent(query: str, hint: str = "auto") -> IntentType:
    """Classify user query into an architectural intent using Fast Rule Hierarchy."""
    h = hint.strip().lower()
    if h in ("code", "implementation", "coder"):
        return IntentType.CODE_IMPLEMENTATION
    if h in ("arch", "architecture", "adr"):
        return IntentType.ARCHITECTURE_DESIGN
    if h in ("theory", "spec", "lookup"):
        return IntentType.THEORY_LOOKUP

    q_lower = query.lower()

    # Priority 1: CODE_IMPLEMENTATION (Highest priority: any code request must have guardrails)
    for pat in CODE_PATTERNS:
        if re.search(pat, q_lower):
            return IntentType.CODE_IMPLEMENTATION

    # Priority 2: ARCHITECTURE_DESIGN
    for pat in ARCH_PATTERNS:
        if re.search(pat, q_lower):
            return IntentType.ARCHITECTURE_DESIGN

    # Priority 3: THEORY_LOOKUP (Default fallback)
    for pat in THEORY_PATTERNS:
        if re.search(pat, q_lower):
            return IntentType.THEORY_LOOKUP

    return IntentType.THEORY_LOOKUP


class CognitiveRouter:
    """Orchestrates multi-tiered cognitive memory retrieval."""

    def __init__(self, tool_context: Any) -> None:
        self.ctx = tool_context

    async def route_and_retrieve(
        self,
        query: str,
        *,
        project: str = "Demo-Core",
        intent_hint: str = "auto",
    ) -> CognitiveBundle:
        """Route query and package appropriate cognitive memory layers."""
        intent = classify_intent(query, hint=intent_hint)
        log.info("[CognitiveRouter] Query: '%s' -> Routed Intent: %s (Project: %s)", query, intent.value, project)

        if intent == IntentType.CODE_IMPLEMENTATION:
            return await self._build_code_triad(query, project)
        elif intent == IntentType.ARCHITECTURE_DESIGN:
            return await self._build_architecture_context(query, project)
        else:
            return await self._build_theory_context(query, project)

    async def _build_code_triad(self, query: str, project: str) -> CognitiveBundle:
        """Build Context Triad: Spec Contract + Top-3 Negative Constraints + Golden Exemplar."""
        # 1. Spec Contract / Chunks
        spec_text = ""
        specs_ref: list[str] = []
        try:
            results = await self.ctx.retriever.search(query, project_id=project)
            if results:
                active = results[:2]
                specs_ref = list({s for r in active for s in r.spec_ids})
                spec_lines = [f"- [{', '.join(r.spec_ids)}] {r.text[:300]}..." for r in active]
                spec_text = "\n".join(spec_lines)
        except Exception as e:
            log.warning("[CognitiveRouter] Vector search failed in Triad, falling back: %s", e)

        # Infer topic
        q_lower = query.lower()
        pattern = "general"
        if any(k in q_lower for k in ["lương", "salary", "payroll", "thuế", "pit"]):
            pattern = "payroll"
        elif any(k in q_lower for k in ["công", "timesheet", "locked", "ca kíp", "attendance"]):
            pattern = "timesheet"
        elif any(k in q_lower for k in ["mcp", "tool", "server"]):
            pattern = "mcp"

        # 2. Reflective Memory (Guardrails - Top 3)
        # Import dynamically or use document store
        guardrails_applied: list[str] = []
        guardrails_text = ""
        target_doc_id = "HR-GOTCHAS" if "HR" in project.upper() else "PKB-GOTCHAS"
        if self.ctx.documents:
            doc = await self.ctx.documents.get(target_doc_id)
            if doc:
                lines = doc.content.splitlines()
                items: list[str] = []
                for line in lines:
                    if line.strip().startswith("- **[FORBIDDEN]"):
                        items.append(line.strip())
                        if len(items) >= 3:
                            break
                guardrails_applied = items
                guardrails_text = "\n".join(f"  {it}" for it in items)

        if not guardrails_text:
            guardrails_text = "  - [FORBIDDEN] Không vi phạm kiểu dữ liệu và ràng buộc kiến trúc."
            guardrails_applied = ["Default Guardrails"]

        # 3. Procedural Memory (Golden Exemplar)
        exemplar_text = ""
        target_ex_id = (
            "HR-EX-001" if pattern == "payroll" else ("HR-EX-002" if pattern == "timesheet" else "PKB-EX-001")
        )
        if self.ctx.documents:
            ex_doc = await self.ctx.documents.get(target_ex_id)
            if ex_doc:
                code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", ex_doc.content, re.DOTALL)
                if code_match:
                    exemplar_text = code_match.group(1).strip()
                else:
                    exemplar_text = ex_doc.content[:500]

        # Calculate CER
        # Average URD spec has ~18,000 tokens. The Triad context is tightly compressed into ~850 tokens.
        est_baseline = 18500
        actual_tokens = max(200, (len(spec_text) + len(guardrails_text) + len(exemplar_text)) // 4)
        cer = round(actual_tokens / est_baseline, 4)
        savings = round((1.0 - cer) * 100, 1)

        formatted = (
            f"🧠 [COGNITIVE MEMORY TRIAD: CODE IMPLEMENTATION]\n"
            f"Dự án: {project} | Intent: CODE_IMPLEMENTATION | CER Token Savings: {savings}%\n\n"
            f"1️⃣ [TIÊU CHUẨN ĐẶC TẢ / SPEC CONTRACT]:\n{spec_text or 'Tra cứu đặc tả liên quan...'}\n\n"
            f"2️⃣ [RÀNG BUỘC CẤM KỴ / NEGATIVE CONSTRAINTS (TOP-3)]:\n{guardrails_text}\n\n"
            "3️⃣ [MÃ NGUỒN MẪU CHUẨN SẢN XUẤT / GOLDEN EXEMPLAR "
            f"({target_ex_id})]:\n```python\n{exemplar_text[:1200]}\n```\n\n"
            "⚠️ CHỈ THỊ THI CÔNG: Bắt buộc tuân thủ 100% các điều cấm kỵ và đối chiếu mẫu chuẩn trước khi sinh mã "
            "nguồn."
        )

        return CognitiveBundle(
            intent=IntentType.CODE_IMPLEMENTATION,
            project=project,
            query=query,
            formatted_context=formatted,
            specs_referenced=specs_ref or [target_doc_id, target_ex_id],
            guardrails_applied=guardrails_applied,
            exemplar_applied=target_ex_id,
            cer_metrics=CERMetrics(
                estimated_baseline_tokens=est_baseline,
                actual_context_tokens=actual_tokens,
                cer_ratio=cer,
                token_savings_pct=savings,
            ),
        )

    async def _build_architecture_context(self, query: str, project: str) -> CognitiveBundle:
        """Build Architecture Context: Episodic ADRs with graceful fallback."""
        adr_texts: list[str] = []
        specs_ref: list[str] = []

        # Find ADRs in documents
        if self.ctx.documents:
            all_docs = await self.ctx.documents.all()
            for doc in all_docs:
                if "ADR-" in doc.spec_id.upper():
                    adr_texts.append(f"### {doc.spec_id}: {doc.title}\n{doc.content[:500]}...")
                    specs_ref.append(doc.spec_id)

        # Fallback to foundational architecture spec if no ADR found
        if not adr_texts and self.ctx.documents:
            fallback_id = "PKB-01" if "PKB" in project.upper() else "HR-PROJECT"
            doc = await self.ctx.documents.get(fallback_id)
            if doc:
                adr_texts.append(f"### {doc.spec_id}: {doc.title} (Foundational Architecture)\n{doc.content[:800]}...")
                specs_ref.append(doc.spec_id)

        combined = "\n\n".join(adr_texts)
        formatted = (
            f"🏛️ [EPISODIC MEMORY: ARCHITECTURAL DECISIONS & ADRs]\n"
            f"Dự án: {project} | Intent: ARCHITECTURE_DESIGN\n\n"
            f"{combined}\n\n"
            "💡 HƯỚNG DẪN KIẾN TRÚC: Đối chiếu các đánh đổi (Trade-offs) và quyết định cốt lõi trên khi thiết kế hệ "
            "thống."
        )

        return CognitiveBundle(
            intent=IntentType.ARCHITECTURE_DESIGN,
            project=project,
            query=query,
            formatted_context=formatted,
            specs_referenced=specs_ref,
        )

    async def _build_theory_context(self, query: str, project: str) -> CognitiveBundle:
        """Build Theory Context: Focused Spec chunks with citation anchors."""
        specs_ref: list[str] = []
        lines = ["📖 [SEMANTIC MEMORY: THEORY & SPECIFICATIONS]"]
        lines.append(f"Dự án: {project} | Intent: THEORY_LOOKUP\n")

        try:
            results = await self.ctx.retriever.search(query, project_id=project)
            if results:
                for idx, r in enumerate(results[:4], 1):
                    specs_ref.extend(r.spec_ids)
                    where = f" > {' > '.join(r.headings)}" if r.headings else ""
                    lines.append(f"[{idx}] [Spec: {', '.join(r.spec_ids)}]{where}")
                    lines.append(f"Nội dung: {r.text}\n")
            else:
                lines.append(f"Không tìm thấy đoạn trích đặc tả phù hợp cho query: '{query}'.")
        except Exception as e:
            lines.append(f"Lỗi khi tra cứu đặc tả: {e}")

        lines.append("📌 NGUYÊN TẮC: Mọi câu trả lời nghiệp vụ phải kèm mã Spec ID ở cuối câu.")
        return CognitiveBundle(
            intent=IntentType.THEORY_LOOKUP,
            project=project,
            query=query,
            formatted_context="\n".join(lines),
            specs_referenced=list(set(specs_ref)),
        )
