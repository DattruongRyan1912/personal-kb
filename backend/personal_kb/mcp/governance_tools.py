"""MCP tools that write: requirement proposals (human gate) and the worklog (agents write it directly)."""

import logging
import os

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from personal_kb.mcp.context import context_holder

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


_WORKLOG_NOT_CONFIGURED = "Lỗi: worklog chưa được cấu hình (không có kho Postgres)"


def _caller(request: Context) -> tuple[str, str]:
    """The agent and session an entry comes from, for the many agents that leave both empty (2026-10-29: 42 of 43
    MyNotch entries had no session): the MCP client's name, and the session Claude Code gave this server."""
    try:
        params = request.session.client_params
    except ValueError:  # called outside an MCP request
        params = None
    agent = params.client_info.name if params and params.client_info else ""
    # Claude Code starts one MCP server per session with its id (the transcript's file name) in the environment; an
    # AGY started from a Claude shell inherits it, so it counts only for a Claude client
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "") if agent.startswith("claude") else ""
    return agent, session


def register_governance_tools(server: MCPServer) -> None:
    @server.tool(
        name="propose_knowledge_update",
        annotations=WRITE_ANNOTATIONS,
        description=(
            "Đề xuất cập nhật hoặc bổ sung tri thức mới vào tài liệu Spec. Hệ thống sẽ TỰ ĐỘNG PHÊ DUYỆT và "
            "ÁP DỤNG TRỰC TIẾP vào tài liệu Markdown và kho tri thức (trừ khi phát hiện xung đột vi phạm "
            "Negative Constraints). LƯU Ý QUAN TRỌNG: Hệ thống có cơ chế Chống trùng lặp (Deduplication). "
            "Nếu nội dung đã có trong tài liệu gốc hoặc đã có đề xuất tương tự, yêu cầu sẽ bị từ chối. "
            "Agent BẮT BUỘC nên gọi 'search_knowledge' hoặc 'get_spec_content' để kiểm tra trước xem "
            "nội dung đã có chưa."
        ),
    )
    async def propose_knowledge_update(
        spec_id: str,
        title: str,
        proposed_content: str,
        rationale: str,
        section: str = "",
    ) -> str:
        """Create a knowledge update proposal, auto-applying and syncing unless blocked by conflicts."""
        from datetime import UTC, datetime

        from personal_kb.services.proposals import DuplicateProposalError, ProposalStore, resolve_spec_path

        store = ProposalStore()
        try:
            prop = store.create(
                spec_id=spec_id.strip(),
                title=title.strip(),
                section=section.strip(),
                proposed_content=proposed_content.strip(),
                rationale=rationale.strip(),
                auto_approve=True,
            )
            if prop.conflict_detected:
                return (
                    f"⚠️ ĐÃ TẠO ĐỀ XUẤT (CHẶN TỰ ĐỘNG DUYỆT DO CẢNH BÁO XUNG ĐỘT QUY TẮC CẤM):\n"
                    f"- Mã đề xuất: {prop.id}\n"
                    f"- Tài liệu: {prop.spec_id}\n"
                    f"- Tiêu đề: {prop.title}\n"
                    f"- Mục cập nhật: {prop.section or 'Toàn văn'}\n"
                    f"- Trạng thái: {prop.status} (CẢNH BÁO XUNG ĐỘT: [{prop.conflict_rule_id}])\n"
                    f"- Lý do xung đột: {prop.conflict_reason}\n"
                    f"- Lưu ý: Đề xuất này vi phạm Negative Constraint nên KHÔNG được tự động áp dụng. "
                    f"Đã đưa vào hàng đợi /approvals chờ Human Gate xem xét (yêu cầu force=True để ghi đè)."
                )

            # Re-ingest document into vector database if runtime context is active
            ingest_status = "Đã ghi trực tiếp vào tài liệu Markdown"
            try:
                ctx = context_holder.get()
                embedder = getattr(getattr(ctx, "retriever", None), "embedder", None)
                vectors = getattr(getattr(ctx, "retriever", None), "vectors", None)
                documents = getattr(ctx, "documents", None)
                if embedder is not None and vectors is not None and documents is not None:
                    spec_file = resolve_spec_path(store.knowledge_dir, prop.spec_id)
                    if spec_file.is_file():
                        from personal_kb.services.ingestion import ingest_documents

                        await ingest_documents(
                            [spec_file],
                            embedder=embedder,
                            vectors=vectors,
                            documents=documents,
                            observed_at=datetime.now(UTC),
                        )
                        ingest_status = "Đã ghi trực tiếp vào spec và đồng bộ thành công vào Vector Database"
            except Exception as e:
                log.warning("[GovernanceTools] Instant vector sync skipped (will re-index at next cycle): %s", e)

            return (
                f"✅ ĐÃ TẠO ĐỀ XUẤT CẬP NHẬT TRI THỨC (TỰ ĐỘNG PHÊ DUYỆT & ÁP DỤNG):\n"
                f"- Mã đề xuất: {prop.id}\n"
                f"- Tài liệu: {prop.spec_id}\n"
                f"- Tiêu đề: {prop.title}\n"
                f"- Mục cập nhật: {prop.section or 'Toàn văn'}\n"
                f"- Trạng thái: {prop.status} ({ingest_status})\n"
                f"- Lý do: {prop.rationale}"
            )
        except DuplicateProposalError as exc:
            return (
                f"⚠️ TỪ CHỐI TẠO ĐỀ XUẤT (TRÙNG LẶP NỘI DUNG):\n"
                f"- {exc}\n"
                f"- Hướng dẫn: Đề xuất này đã tồn tại hoặc đã được xử lý. Agent không cần lặp lại yêu cầu."
            )

    @server.tool(
        name="log_progress",
        annotations=WRITE_ANNOTATIONS,
        description=(
            "Ghi thẳng một mục vào worklog của dự án, không cần duyệt; đây là nhật ký tiến độ, không phải requirement. "
            "Gọi khi xong một bước đáng kể, khi ra quyết định, khi gặp cạm bẫy (gotcha), và trước khi kết thúc hoặc "
            "bàn giao phiên làm việc. Khi người dùng nói 'cập nhật tiến độ' thì dùng tool này thay vì "
            "propose_knowledge_update (chỉ dành cho requirement/spec cần Human Gate). "
            "Tham số: 'project', 'summary', 'kind' (progress|decision|gotcha|handoff), 'next_steps', 'agent', "
            "'session_id', 'branch'."
        ),
    )
    async def log_progress(
        project: str,
        summary: str,
        kind: str = "progress",
        next_steps: str = "",
        agent: str = "",
        session_id: str = "",
        branch: str = "",
        *,
        request: Context,
    ) -> str:
        """Append a worklog entry."""
        from personal_kb.core.exceptions import DependencyUnavailableError
        from personal_kb.services.worklog import NewWorklogEntry, WorklogValidationError, validate_entry

        caller_agent, caller_session = _caller(request)
        ctx = context_holder.get()
        if ctx.worklog is None:
            return _WORKLOG_NOT_CONFIGURED
        try:
            entry = validate_entry(
                NewWorklogEntry(
                    project=project,
                    kind=kind,
                    summary=summary,
                    next_steps=next_steps,
                    agent=agent.strip() or caller_agent,
                    session_id=session_id.strip() or caller_session,
                    branch=branch,
                ),
                ctx.projects,
            )
            stored = await ctx.worklog.add(entry)
        except (WorklogValidationError, DependencyUnavailableError) as exc:
            return f"Lỗi: {exc}"
        return f"✅ Đã ghi worklog #{stored.id} cho {stored.project}"

    @server.tool(
        name="get_worklog",
        annotations=READ_ONLY_ANNOTATIONS,
        description=(
            "Đọc nhật ký tiến độ (worklog) gần nhất của một dự án (hoặc toàn bộ dự án nếu để trống), mới nhất trước, "
            "để tiếp tục công việc agent khác đã làm dở. Tham số: 'project' (để trống = tất cả dự án), "
            "'limit' (1-50, mặc định 10) và 'kind' (progress|decision|gotcha|handoff; rỗng = tất cả)."
        ),
    )
    async def get_worklog(project: str = "", limit: int = 10, kind: str = "") -> str:
        """Read recent worklog entries."""
        from personal_kb.core.exceptions import DependencyUnavailableError

        ctx = context_holder.get()
        if ctx.worklog is None:
            return _WORKLOG_NOT_CONFIGURED
        project = project.strip()
        try:
            entries = await ctx.worklog.recent(project, limit=max(1, min(limit, 50)), kind=kind.strip())
        except DependencyUnavailableError as exc:
            return f"Lỗi: {exc}"
        if not entries:
            return f"Chưa có worklog cho {project}." if project else "Chưa có worklog."
        lines = []
        for e in entries:
            if project:
                lines.append(f"#{e.id} {e.created_at:%Y-%m-%d %H:%M} [{e.agent}/{e.kind}] {e.summary}")
            else:
                lines.append(f"#{e.id} {e.created_at:%Y-%m-%d %H:%M} [{e.project}] [{e.agent}/{e.kind}] {e.summary}")
            if e.next_steps:
                lines.append(f"  → tiếp: {e.next_steps}")
        return "\n".join(lines)
