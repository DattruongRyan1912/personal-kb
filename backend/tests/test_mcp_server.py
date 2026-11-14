from dataclasses import fields

import pytest
from pydantic import AnyUrl

from personal_kb.mcp.server import create_mcp_server, setup_mcp_context
from personal_kb.services.memory_ports import SpecDocument
from personal_kb.services.retrieval import SearchResult
from personal_kb.services.worklog import NewWorklogEntry, WorklogEntry
from personal_kb.tools.base import ToolContext


class DummyRetriever:
    async def search(self, query: str, as_of=None, project_id: str | None = None):
        if "ot" in query.lower():
            return [
                SearchResult(
                    text="Hệ số làm thêm giờ ngày lễ là 300%.",
                    score=0.89,
                    source="vector",
                    spec_ids=["HR-M04"],
                    headings=["Quy định làm thêm giờ", "Hệ số lương OT"],
                )
            ]
        return []


class DummyDocuments:
    def __init__(self):
        self._docs = {
            "HR-M04": SpecDocument(
                spec_id="HR-M04",
                title="Quản lý Chấm công và Tính lương",
                content=(
                    "---\nid: HR-M04\ntitle: Quản lý Chấm công và Tính lương\nowner: Ryan Truong\nstatus: active\n---\n"
                    "# 1. Tổng quan\nQuy định làm thêm giờ..."
                ),
            ),
            "HR-GOTCHAS": SpecDocument(
                spec_id="HR-GOTCHAS",
                title="Demo-Core Negative Constraints & Architecture Guardrails",
                content=(
                    "---\nid: HR-GOTCHAS\ntitle: Demo-Core Negative Constraints\nproject: Demo-Core\n---\n"
                    "# Demo-Core Guardrails\n"
                    "## 1. Cross-Cutting\n"
                    "- **[FORBIDDEN] [NC-HR-001] [Tiền tệ & Số học chính xác]:**\n"
                    "  - CẤM dùng float, bắt buộc dùng Decimal.\n"
                    "## 5. HR-M04: Payroll\n"
                    "- **[FORBIDDEN] [NC-HR-040] [Hardcode Tham số Lương]:**\n"
                    "  - CẤM hardcode hệ số làm thêm ca đêm 1.3.\n"
                    "- **[FORBIDDEN] [NC-HR-041] [Cân bằng Bảng lương]:**\n"
                    "  - CẤM sai số Net Pay khác 0.\n"
                ),
            ),
            "MYNOTCH-GOTCHAS": SpecDocument(
                spec_id="MYNOTCH-GOTCHAS",
                title="MyNotch Guardrails & Negative Constraints",
                content=(
                    "---\nid: MYNOTCH-GOTCHAS\ntitle: MyNotch Guardrails\nproject: MyNotch\n---\n"
                    "# MyNotch Guardrails\n"
                    "## 1. Signing & TCC\n"
                    "- **[FORBIDDEN] [NC-MYN-001] [Cấm Build Ad-hoc Signing]:**\n"
                    "  - CẤM dùng ad-hoc signing làm mất TCC.\n"
                    "- **[FORBIDDEN] [NC-MYN-002] [Cấm Dùng cp -R]:**\n"
                    "  - CẤM dùng cp -R làm hỏng code signature.\n"
                    "### [NC-MYN-026] [Smart Selection Chip Auto-Dismiss Invariant]\n"
                    "  - AutoDismiss mặc định là false.\n"
                ),
            ),
        }

    async def get(self, spec_id: str):
        return self._docs.get(spec_id)

    async def all(self):
        return list(self._docs.values())


@pytest.fixture
def mcp_context():
    ctx = ToolContext(retriever=DummyRetriever(), documents=DummyDocuments())
    setup_mcp_context(ctx)
    return ctx


async def test_mcp_search_knowledge_tool(mcp_context):
    server = create_mcp_server()
    res = await server.call_tool("search_knowledge", {"query": "Quy định OT"})
    assert not res.is_error
    content = res.content[0].text
    assert "HR-M04" in content
    assert "Hệ số làm thêm giờ ngày lễ là 300%" in content
    assert "0.89" in content


async def test_mcp_get_spec_content_tool(mcp_context):
    server = create_mcp_server()
    res = await server.call_tool("get_spec_content", {"spec_id": "HR-M04"})
    assert not res.is_error
    content = res.content[0].text
    assert "# HR-M04 — Quản lý Chấm công và Tính lương" in content
    assert "Quy định làm thêm giờ..." in content


async def test_mcp_get_spec_content_not_found(mcp_context):
    server = create_mcp_server()
    res = await server.call_tool("get_spec_content", {"spec_id": "NON_EXISTENT"})
    assert "Không tìm thấy" in res.content[0].text


async def test_mcp_list_specs_tool(mcp_context):
    server = create_mcp_server()
    res = await server.call_tool("list_specs", {})
    assert not res.is_error
    content = res.content[0].text
    assert "HR-M04" in content
    assert "Quản lý Chấm công và Tính lương" in content
    assert "Ryan Truong" in content


async def test_mcp_resource_read_spec(mcp_context):
    server = create_mcp_server()
    contents = await server.read_resource(AnyUrl("spec://HR-M04"))
    assert len(contents) == 1
    assert "HR-M04" in contents[0].content


async def test_mcp_verify_citation_valid(mcp_context):
    server = create_mcp_server()
    res = await server.call_tool("verify_citation", {"spec_id": "HR-M04", "quote": "Quy định làm thêm giờ"})
    assert not res.is_error
    content = res.content[0].text
    assert "✅ XÁC THỰC THÀNH CÔNG" in content
    assert "HR-M04" in content
    assert "1. Tổng quan" in content
    assert "view_url" in content


async def test_mcp_verify_citation_invalid_quote(mcp_context):
    server = create_mcp_server()
    res = await server.call_tool("verify_citation", {"spec_id": "HR-M04", "quote": "Công thức tính tên lửa sao hoả"})
    assert not res.is_error
    content = res.content[0].text
    assert "⚠️ CẢNH BÁO" in content
    assert "Không tìm thấy" in content


async def test_mcp_verify_citation_spec_not_found(mcp_context):
    server = create_mcp_server()
    res = await server.call_tool("verify_citation", {"spec_id": "UNKNOWN", "quote": "some text"})
    assert "không tồn tại" in res.content[0].text


async def test_mcp_propose_knowledge_update_tool(mcp_context):
    import re
    import uuid
    from pathlib import Path
    from personal_kb.services.proposals import ProposalStore, resolve_spec_path

    # Save original spec content to prevent side-effect dirtying of the git working tree
    store = ProposalStore()
    spec_path = resolve_spec_path(store.knowledge_dir, "HR-M04")
    original_spec_content = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else None

    unique_key = uuid.uuid4().hex[:8]
    server = create_mcp_server()
    payload = {
        "spec_id": "HR-M04",
        "title": f"Bổ sung quy định mới {unique_key}",
        "section": f"Chế độ đặc thù {unique_key}",
        "proposed_content": f"Chính sách độc quyền {unique_key}.",
        "rationale": "Căn cứ thỏa ước lao động tập thể.",
    }

    content1 = ""
    try:
        # 1. First call creates proposal successfully
        res1 = await server.call_tool("propose_knowledge_update", payload)
        assert not res1.is_error
        content1 = res1.content[0].text
        assert "✅ ĐÃ TẠO ĐỀ XUẤT CẬP NHẬT TRI THỨC" in content1
        assert "HR-M04" in content1
        assert unique_key in content1

        # 2. Duplicate call is rejected with duplicate warning
        res2 = await server.call_tool("propose_knowledge_update", payload)
        assert not res2.is_error
        content2 = res2.content[0].text
        assert "⚠️ TỪ CHỐI TẠO ĐỀ XUẤT (TRÙNG LẶP NỘI DUNG)" in content2
    finally:
        # Clean up test proposal artifact
        match = re.search(r"PROP-[A-Za-z0-9-]+", content1)
        if match:
            prop_id = match.group(0)
            for base in [Path("knowledge/proposals"), Path("../knowledge/proposals")]:
                target = base / f"{prop_id}.json"
                if target.is_file():
                    target.unlink(missing_ok=True)

        # Restore original spec file content on disk
        if original_spec_content is not None and spec_path.is_file():
            spec_path.write_text(original_spec_content, encoding="utf-8")


async def test_mcp_recall_guardrails_tool(mcp_context):
    server = create_mcp_server()
    # 1. Recall without topic
    res = await server.call_tool("recall_guardrails", {"project": "Demo-Core"})
    assert not res.is_error
    content = res.content[0].text
    assert "ACTIVE GUARDRAILS & NEGATIVE CONSTRAINTS" in content
    assert "HR-GOTCHAS" in content
    assert "NC-HR-001" in content

    # 2. Recall with topic payroll
    res_topic = await server.call_tool("recall_guardrails", {"project": "Demo-Core", "topic": "payroll"})
    assert not res_topic.is_error
    content_topic = res_topic.content[0].text
    assert "NC-HR-040" in content_topic
    assert "NC-HR-041" in content_topic
    assert "Hardcode Tham số Lương" in content_topic

    # 3. Recall with non-existent project
    res_empty = await server.call_tool("recall_guardrails", {"project": "UNKNOWN_PROJ"})
    assert "chưa có tài liệu Guardrails/Gotchas" in res_empty.content[0].text

    # 4. Recall with MyNotch project (both bullet and heading formats)
    res_mynotch = await server.call_tool("recall_guardrails", {"project": "MyNotch"})
    assert not res_mynotch.is_error
    content_mynotch = res_mynotch.content[0].text
    assert "MYNOTCH-GOTCHAS" in content_mynotch
    assert "NC-MYN-001" in content_mynotch
    assert "NC-MYN-002" in content_mynotch
    assert "NC-MYN-026" in content_mynotch

    # 5. ADR-003 Top-3 Hard limit enforcement even with larger limit requested
    res_limit = await server.call_tool("recall_guardrails", {"project": "Demo-Core", "limit": 10})
    assert not res_limit.is_error
    assert "Số lượng áp dụng: 3 (Áp dụng luật Top-3 Hard Limit để bảo vệ Context Window)" in res_limit.content[0].text


class FakeWorklogStore:
    def __init__(self):
        self.entries = []

    async def ensure(self):
        pass

    async def add(self, entry):
        from datetime import datetime

        stored = WorklogEntry(
            **{f.name: getattr(entry, f.name) for f in fields(NewWorklogEntry)},
            id=len(self.entries) + 1,
            created_at=datetime(2026, 10, 24, 9, 5 + len(self.entries)),
        )
        self.entries.append(stored)
        return stored

    async def recent(self, project="", *, limit=10, kind=""):
        rows = [e for e in self.entries if (not project or e.project == project) and (not kind or e.kind == kind)]
        return list(reversed(rows))[:limit]


def _worklog_context(store):
    ctx = ToolContext(
        retriever=DummyRetriever(),
        documents=DummyDocuments(),
        worklog=store,
        projects=frozenset({"Demo-Core"}),
    )
    setup_mcp_context(ctx)
    return ctx


async def test_log_progress_writes_and_returns_id():
    store = FakeWorklogStore()
    _worklog_context(store)
    res = await create_mcp_server().call_tool(
        "log_progress", {"project": "Demo-Core", "summary": "xong bước 1", "agent": "claude", "next_steps": "bước 2"}
    )
    assert res.content[0].text == "✅ Đã ghi worklog #1 cho Demo-Core"
    assert store.entries[0].summary == "xong bước 1"
    assert store.entries[0].agent == "claude"
    assert store.entries[0].kind == "progress"


async def test_log_progress_unknown_project_is_error_text():
    store = FakeWorklogStore()
    _worklog_context(store)
    res = await create_mcp_server().call_tool("log_progress", {"project": "Nope", "summary": "x"})
    assert res.content[0].text.startswith("Lỗi:")
    assert store.entries == []


async def test_log_progress_without_store_is_error_text():
    _worklog_context(None)
    res = await create_mcp_server().call_tool("log_progress", {"project": "Demo-Core", "summary": "x"})
    assert res.content[0].text == "Lỗi: worklog chưa được cấu hình (không có kho Postgres)"


async def test_get_worklog_lists_newest_first_with_next_steps():
    store = FakeWorklogStore()
    _worklog_context(store)
    server = create_mcp_server()
    await server.call_tool("log_progress", {"project": "Demo-Core", "summary": "một", "agent": "agy"})
    await server.call_tool(
        "log_progress",
        {"project": "Demo-Core", "summary": "hai", "kind": "handoff", "agent": "claude", "next_steps": "làm tiếp"},
    )
    text = (await server.call_tool("get_worklog", {"project": "Demo-Core"})).content[0].text
    lines = text.splitlines()
    assert lines[0] == "#2 2026-10-24 09:06 [claude/handoff] hai"
    assert lines[1] == "  → tiếp: làm tiếp"
    assert lines[2] == "#1 2026-10-24 09:05 [agy/progress] một"
    args = {"project": "Demo-Core", "kind": "handoff", "limit": 0}
    only = (await server.call_tool("get_worklog", args)).content[0].text
    assert only.count("#") == 1


async def test_get_worklog_empty_project_message():
    _worklog_context(FakeWorklogStore())
    res = await create_mcp_server().call_tool("get_worklog", {"project": "Demo-Core"})
    assert res.content[0].text == "Chưa có worklog cho Demo-Core."


async def test_get_worklog_without_project_returns_all_projects():
    store = FakeWorklogStore()
    ctx = ToolContext(
        retriever=DummyRetriever(),
        documents=DummyDocuments(),
        worklog=store,
        projects=frozenset({"Demo-Core", "MyNotch"}),
    )
    setup_mcp_context(ctx)
    server = create_mcp_server()
    await server.call_tool("log_progress", {"project": "Demo-Core", "summary": "tác vụ 1", "agent": "agy"})
    await server.call_tool("log_progress", {"project": "MyNotch", "summary": "tác vụ 2", "agent": "claude"})

    # Call without project parameter
    res = await server.call_tool("get_worklog", {"limit": 5})
    text = res.content[0].text
    lines = text.splitlines()
    assert lines[0] == "#2 2026-10-24 09:06 [MyNotch] [claude/progress] tác vụ 2"
    assert lines[1] == "#1 2026-10-24 09:05 [Demo-Core] [agy/progress] tác vụ 1"

    # Call with empty store and no project
    _worklog_context(FakeWorklogStore())
    empty_res = await server.call_tool("get_worklog", {})
    assert empty_res.content[0].text == "Chưa có worklog."

    # Check tool input schema doesn't require project
    tools = await server.list_tools()
    worklog_tool = next(t for t in tools if t.name == "get_worklog")
    assert "project" not in worklog_tool.input_schema.get("required", [])


async def test_search_knowledge_warns_when_the_results_were_not_reranked():
    class UnrankedRetriever:
        async def search(self, query, as_of=None, project_id=None):
            return [SearchResult(text="t", score=0.5, source="vector", spec_ids=["HR-M04"], reranked=False)]

    setup_mcp_context(ToolContext(retriever=UnrankedRetriever(), documents=DummyDocuments()))
    res = await create_mcp_server().call_tool("search_knowledge", {"query": "q"})

    assert res.content[0].text.startswith("⚠️ Reranker")


async def test_log_progress_names_the_agent_and_session_an_agent_leaves_empty(monkeypatch):
    # 42 of 43 MyNotch entries had no session and 30 no agent (2026-10-29): the client and Claude Code know both
    from mcp import Client
    from mcp.types import Implementation

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "b9dd4d76")
    store = FakeWorklogStore()
    _worklog_context(store)
    server = create_mcp_server()
    async with Client(server, client_info=Implementation(name="claude-code", version="2")) as client:
        await client.call_tool("log_progress", {"project": "Demo-Core", "summary": "một"})
        await client.call_tool(
            "log_progress", {"project": "Demo-Core", "summary": "hai", "agent": "claude", "session_id": "s1"}
        )

    assert [(e.agent, e.session_id) for e in store.entries] == [("claude-code", "b9dd4d76"), ("claude", "s1")]


async def test_another_client_does_not_take_the_claude_session_it_inherited(monkeypatch):
    # an AGY started from a Claude shell inherits CLAUDE_CODE_SESSION_ID
    from mcp import Client
    from mcp.types import Implementation

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "b9dd4d76")
    store = FakeWorklogStore()
    _worklog_context(store)
    async with Client(create_mcp_server(), client_info=Implementation(name="antigravity", version="1")) as client:
        await client.call_tool("log_progress", {"project": "Demo-Core", "summary": "một"})

    assert [(e.agent, e.session_id) for e in store.entries] == [("antigravity", "")]


async def test_log_progress_does_not_ask_the_agent_for_its_request_context():
    tool = next(t for t in await create_mcp_server().list_tools() if t.name == "log_progress")
    assert "request" not in tool.input_schema["properties"]


async def test_mcp_tools_declare_explicit_safety_annotations():
    server = create_mcp_server()
    tools = await server.list_tools()
    tools_by_name = {t.name: t for t in tools}

    read_only_tools = {
        "search_knowledge",
        "verify_citation",
        "get_spec_content",
        "list_specs",
        "recall_guardrails",
        "recall_exemplar",
        "query_cognitive_memory",
        "get_worklog",
        "kb_code_status",
        "kb_code_search",
        "kb_code_node",
        "kb_code_callers",
        "kb_code_callees",
        "kb_code_impact",
    }
    write_tools = {
        "propose_knowledge_update",
        "log_progress",
        "kb_code_index",
    }

    assert set(tools_by_name.keys()) == read_only_tools | write_tools

    for name in read_only_tools:
        tool = tools_by_name[name]
        assert tool.annotations is not None, f"Tool {name} missing annotations"
        assert tool.annotations.read_only_hint is True, f"Tool {name} should be readOnlyHint=True"
        assert tool.annotations.destructive_hint is False, f"Tool {name} should be destructiveHint=False"
        assert tool.annotations.open_world_hint is False, f"Tool {name} should be openWorldHint=False"

    for name in write_tools:
        tool = tools_by_name[name]
        assert tool.annotations is not None, f"Tool {name} missing annotations"
        assert tool.annotations.read_only_hint is False, f"Tool {name} should be readOnlyHint=False"
        assert tool.annotations.destructive_hint is False, f"Tool {name} should be destructiveHint=False"
        assert tool.annotations.open_world_hint is False, f"Tool {name} should be openWorldHint=False"
