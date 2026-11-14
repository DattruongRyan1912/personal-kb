---
id: PKB-EX-001
title: "Production MCP Tool Implementation Pattern"
project: Personal-KB
memory_tier: procedural
item_type: golden_exemplar
language: python
author: "Senior Architect & QA Advisor"
version: "1.0.0"
last_updated: "2026-10-21"
---

# PKB-EX-001: Mẫu Triển Khai Công Cụ MCP Chuẩn Mực (Production MCP Tool)

> [!NOTE]
> Mẫu mã nguồn sản xuất tiêu chuẩn phục vụ mở rộng **MCP Server (`personal_kb/mcp/server.py`)**.
> Tuân thủ các nguyên tắc:
> - Giữ sạch 100% `sys.stdout` cho JSON-RPC protocol framing (mọi logging ghi ra `sys.stderr`).
> - Bắt buộc xử lý Exception Boundary (không làm crash daemon MCP server).
> - Trả về định dạng Markdown cấu trúc rõ ràng kèm trích dẫn có thể nhấp chuột (`spec://...` hoặc URL).

```python
import logging
import sys
from typing import Any, Dict, Optional
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

# 1. BẮT BUỘC: Redirect logging sang sys.stderr để bảo vệ tính toàn vẹn của JSON-RPC trên stdout
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("personal_kb.mcp.tool_example")


class ToolContextHolder:
    """Singleton giữ runtime context (database connection, vector store, document store)."""
    def __init__(self) -> None:
        self.ctx: Optional[Any] = None

    def get(self) -> Any:
        if self.ctx is None:
            raise RuntimeError("ToolContext chưa được khởi tạo. Hãy gọi setup_context(ctx) trước.")
        return self.ctx


_context_holder = ToolContextHolder()


def register_production_tool(server: MCPServer) -> None:
    """Đăng ký công cụ MCP với đầy đủ docstring, tham số chặt chẽ và error handling."""

    @server.tool(
        name="query_project_metrics",
        description=(
            "Truy vấn các chỉ số kiểm toán, độ phủ tri thức và trạng thái đồng bộ của dự án. "
            "Dùng khi cần đánh giá sức khỏe tài liệu hoặc kiểm toán dữ liệu."
        ),
    )
    async def query_project_metrics(project: str, include_archived: bool = False) -> str:
        """Hàm thực thi công cụ MCP theo chuẩn an toàn cao nhất."""
        p = project.strip()
        if not p:
            return "❌ Lỗi: Tham số 'project' không được để trống (ví dụ: 'Demo-Core', 'Personal-KB')."

        try:
            ctx = _context_holder.get()
            log.info("[MCP] Đang truy vấn metrics cho dự án: %s (include_archived=%s)", p, include_archived)

            # Thực thi logic nghiệp vụ an toàn
            docs = await ctx.documents.all()
            project_docs = [d for d in docs if getattr(d, "project_id", "") == p]

            if not project_docs:
                return f"ℹ️ Dự án '{p}' hiện chưa có tài liệu nào trong kho tri thức."

            total_chunks = sum(len(d.content.split("\n\n")) for d in project_docs)
            active_docs = len(project_docs)

            # Định dạng output: Markdown súc tích, có cấu trúc
            output = [
                f"📊 BÁO CÁO CHỈ SỐ DỰ ÁN: {p}",
                f"- Tổng số tài liệu: {active_docs}",
                f"- Ước tính phân đoạn (chunks): {total_chunks}",
                f"- Trạng thái: Sẵn sàng tra cứu qua hybrid search",
                f"",
                f"🔗 Danh sách tài liệu khả dụng:",
            ]
            for doc in project_docs[:5]:
                output.append(f"  • {doc.spec_id}: {doc.title} (Resource: spec://{doc.spec_id})")

            return "\n".join(output)

        except Exception as exc:
            # Bắt mọi exception tại biên để không ngắt kết nối stdio JSON-RPC
            log.exception("[MCP] Lỗi khi thực thi query_project_metrics: %s", exc)
            return f"❌ THẤT BẠI: Đã xảy ra lỗi nội bộ khi xử lý: {str(exc)}"
```
