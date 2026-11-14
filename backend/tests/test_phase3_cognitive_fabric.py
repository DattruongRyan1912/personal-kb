"""Phase 3 Comprehensive Test Suite: Two-Phase Intent-Gated Cognitive Router & Semantic Anti-Collision Engine.

Tests:
1. Fast Rule Intent Classification & Intent Priority Hierarchy
2. Context Triad Packaging & CER calculation in CognitiveRouter
3. Architecture ADR lookup & graceful fallback
4. Semantic Anti-Collision Engine (Rules NC-HR-001, NC-HR-010, NC-HR-020, NC-HR-021)
5. Proposal Soft-Flagging on Create & Hard-Block on Approve (unless forced)
6. MCP query_cognitive_memory tool execution
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from personal_kb.services.anti_collision import detect_conflicts
from personal_kb.services.cognitive_router import (
    CognitiveRouter,
    IntentType,
    classify_intent,
)
from personal_kb.services.memory_ports import SpecDocument
from personal_kb.services.proposals import (
    ProposalConflictError,
    ProposalStore,
)

# --- 1. Intent Classification Tests ---


def test_classify_intent_priority_hierarchy():
    # Priority 1: CODE_IMPLEMENTATION even if architecture/theory terms present
    q_mixed = "Kiến trúc hệ thống quy định như thế nào, hãy viết hàm python def calculate_salary()"
    assert classify_intent(q_mixed) == IntentType.CODE_IMPLEMENTATION

    # Pure code queries
    assert classify_intent("viết hàm tính lương net pay cho nhân viên") == IntentType.CODE_IMPLEMENTATION
    assert classify_intent("def process_timesheet(data: dict):") == IntentType.CODE_IMPLEMENTATION
    assert classify_intent("triển khai unit test cho module payroll") == IntentType.CODE_IMPLEMENTATION

    # Priority 2: ARCHITECTURE_DESIGN
    assert classify_intent("thiết kế hệ thống và mô hình phân bổ database schema") == IntentType.ARCHITECTURE_DESIGN
    assert classify_intent("các quyết định kiến trúc adr về vector store") == IntentType.ARCHITECTURE_DESIGN

    # Priority 3: THEORY_LOOKUP
    assert classify_intent("quy định mức giảm trừ gia cảnh trong spec HR-M04 là gì") == IntentType.THEORY_LOOKUP
    assert classify_intent("chính sách nghỉ phép năm của nhân sự") == IntentType.THEORY_LOOKUP

    # Explicit hint override
    assert classify_intent("giải thích quy trình", hint="code") == IntentType.CODE_IMPLEMENTATION
    assert classify_intent("hàm tính toán", hint="theory") == IntentType.THEORY_LOOKUP


# --- 2. CognitiveRouter Context Triad & CER Tests ---


@pytest.mark.asyncio
async def test_cognitive_router_code_triad_packaging():
    mock_retriever = MagicMock()
    mock_retriever.search = AsyncMock(
        return_value=[
            MagicMock(
                spec_ids=["HR-M04"],
                headings=["Tính lương"],
                text="Công thức lương Net = Gross - Thuế - BH",
                source="vector",
                score=0.92,
            )
        ]
    )

    mock_doc_store = MagicMock()
    mock_doc_store.get = AsyncMock(
        side_effect=lambda spec_id: {
            "HR-GOTCHAS": SpecDocument(
                spec_id="HR-GOTCHAS",
                title="Cấm kỵ HRM",
                content=(
                    "## Lương\n- **[FORBIDDEN] [NC-HR-001] Cấm float**\n- **[FORBIDDEN] [NC-HR-020] Cấm hardcode "
                    "1.3**\n- **[FORBIDDEN] [NC-HR-021] Cấm sửa locked**"
                ),
            ),
            "HR-EX-001": SpecDocument(
                spec_id="HR-EX-001",
                title="Mẫu tính lương",
                content="```python\nfrom decimal import Decimal\ndef calc_net(): return Decimal('1000')\n```",
            ),
        }.get(spec_id)
    )

    mock_ctx = MagicMock(retriever=mock_retriever, documents=mock_doc_store)
    router = CognitiveRouter(mock_ctx)

    bundle = await router.route_and_retrieve(
        "viết hàm tính lương net_pay cho nhân viên",
        project="Demo-Core",
    )

    assert bundle.intent == IntentType.CODE_IMPLEMENTATION
    assert "COGNITIVE MEMORY TRIAD" in bundle.formatted_context
    assert "TIÊU CHUẨN ĐẶC TẢ" in bundle.formatted_context
    assert "RÀNG BUỘC CẤM KỴ" in bundle.formatted_context
    assert "MÃ NGUỒN MẪU CHUẨN SẢN XUẤT" in bundle.formatted_context
    assert bundle.exemplar_applied == "HR-EX-001"
    assert len(bundle.guardrails_applied) >= 1
    assert bundle.cer_metrics is not None
    assert bundle.cer_metrics.token_savings_pct >= 90.0


@pytest.mark.asyncio
async def test_cognitive_router_architecture_context_and_fallback():
    mock_retriever = MagicMock()
    mock_doc_store = MagicMock()
    mock_doc_store.all = AsyncMock(
        return_value=[
            SpecDocument(
                spec_id="ADR-001", title="Vector Single Collection", content="Quyết định dùng 1 collection duy nhất"
            ),
            SpecDocument(spec_id="ADR-002", title="Dual Protocol", content="Quyết định tách biệt MCP và REST"),
        ]
    )
    mock_ctx = MagicMock(retriever=mock_retriever, documents=mock_doc_store)
    router = CognitiveRouter(mock_ctx)

    bundle = await router.route_and_retrieve(
        "thiết kế kiến trúc hệ thống lưu trữ vector",
        project="Personal-KB",
    )

    assert bundle.intent == IntentType.ARCHITECTURE_DESIGN
    assert "EPISODIC MEMORY: ARCHITECTURAL DECISIONS & ADRs" in bundle.formatted_context
    assert "ADR-001" in bundle.formatted_context
    assert "ADR-002" in bundle.formatted_context


# --- 3. Semantic Anti-Collision Detection Tests ---


def test_anti_collision_detects_forbidden_patterns():
    # NC-HR-001: float for salary
    res1 = detect_conflicts(
        spec_id="HR-M04",
        proposed_content="Trường net_pay có kiểu dữ liệu là float để dễ tính toán trên mobile.",
    )
    assert res1.conflict_detected is True
    assert res1.rule_id == "NC-HR-001"

    # NC-HR-010: Hard delete employee
    res2 = detect_conflicts(
        spec_id="HR-M01",
        proposed_content="Khi nhân viên thôi việc, hệ thống thực thi: DELETE FROM employees WHERE id = :emp_id",
    )
    assert res2.conflict_detected is True
    assert res2.rule_id == "NC-HR-010"

    # NC-HR-020: Hardcoded night shift multiplier 1.3
    res3 = detect_conflicts(
        spec_id="HR-M02",
        proposed_content="Tiền ca đêm được gán mặc định bằng lương giờ * 1.3 trong service.",
    )
    assert res3.conflict_detected is True
    assert res3.rule_id == "NC-HR-020"

    # NC-HR-021: Direct update on locked timesheet
    res4 = detect_conflicts(
        spec_id="HR-M02",
        proposed_content="Cho phép chỉnh sửa trực tiếp kỳ công đã khóa khi quản lý gửi email.",
    )
    assert res4.conflict_detected is True
    assert res4.rule_id == "NC-HR-021"

    # NC-PKB-001: Bypass human gate
    res5 = detect_conflicts(
        spec_id="PKB-01",
        proposed_content="Cấu hình auto_approve=true để tự động duyệt không cần người xem xét.",
    )
    assert res5.conflict_detected is True
    assert res5.rule_id == "NC-PKB-001"

    # Clean proposal
    res_clean = detect_conflicts(
        spec_id="HR-M04",
        proposed_content="Bổ sung mức phụ cấp trách nhiệm 2,000,000 VND sử dụng kiểu Decimal(18,2).",
    )
    assert res_clean.conflict_detected is False
    assert res_clean.rule_id is None


# --- 4. Proposal Staging with Anti-Collision Tests ---


@pytest.mark.asyncio
async def test_proposal_soft_flagging_and_hard_block_on_approval(tmp_path):
    store = ProposalStore(knowledge_dir=tmp_path)
    spec_file = tmp_path / "HR-M04.md"
    spec_file.write_text("# HR-M04: Lương\n## Chính sách lương\nNội dung ban đầu.", encoding="utf-8")

    # 1. Create a proposal violating NC-HR-001 (float for salary)
    prop = store.create(
        spec_id="HR-M04",
        title="Đổi kiểu dữ liệu sang float",
        section="Chính sách lương",
        proposed_content="Sử dụng kiểu float cho trường salary và net_pay.",
        rationale="Tiết kiệm bộ nhớ RAM",
    )

    # Soft-flagging: created successfully in PENDING status, but flagged!
    assert prop.status == "PENDING"
    assert prop.conflict_detected is True
    assert prop.conflict_rule_id == "NC-HR-001"
    assert "NC-HR-001" in prop.conflict_reason

    # 2. Approve without force -> MUST BE HARD-BLOCKED with ProposalConflictError
    mock_vectors = MagicMock()
    mock_docs = MagicMock()
    with pytest.raises(ProposalConflictError) as exc_info:
        await store.approve(
            prop.id,
            reviewer="Ryan Truong",
            embedder=MagicMock(),
            vectors=mock_vectors,
            documents=mock_docs,
            force=False,
        )
    assert "vi phạm Negative Constraint [NC-HR-001]" in str(exc_info.value)
    assert "force=True" in str(exc_info.value)

    # 3. Approve with force=True -> Override allowed by Senior Architect
    mock_embedder = MagicMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1] * 1024])
    mock_vectors.apply_revision = AsyncMock()
    mock_vectors.known_chunk_keys = AsyncMock(return_value=set())
    mock_vectors.set_project = AsyncMock(return_value=0)
    mock_docs.put = AsyncMock()

    approved_prop = await store.approve(
        prop.id,
        reviewer="Ryan Truong (Override)",
        embedder=mock_embedder,
        vectors=mock_vectors,
        documents=mock_docs,
        force=True,
    )
    assert approved_prop.status == "APPROVED"
    assert approved_prop.reviewed_by == "Ryan Truong (Override)"


# --- 5. MCP Tool Execution Test ---


@pytest.mark.asyncio
async def test_mcp_query_cognitive_memory():
    from personal_kb.mcp.server import create_mcp_server, setup_mcp_context
    from personal_kb.tools.base import ToolContext

    mock_retriever = MagicMock()
    mock_retriever.search = AsyncMock(
        return_value=[
            MagicMock(
                spec_ids=["HR-M04"], headings=["Tính lương"], text="Công thức lương chuẩn", source="vector", score=0.9
            )
        ]
    )
    mock_docs = MagicMock()
    mock_docs.get = AsyncMock(
        return_value=SpecDocument(spec_id="HR-GOTCHAS", title="Gotchas", content="- **[FORBIDDEN] cấm float**")
    )

    ctx = ToolContext(retriever=mock_retriever, documents=mock_docs)
    setup_mcp_context(ctx)

    server = create_mcp_server()
    res = await server.call_tool(
        "query_cognitive_memory",
        {"query": "viết hàm tính lương cho nhân sự", "project": "Demo-Core", "intent_hint": "code"},
    )
    assert not res.is_error
    text = res.content[0].text
    assert "COGNITIVE MEMORY TRIAD" in text
    assert "Demo-Core" in text
