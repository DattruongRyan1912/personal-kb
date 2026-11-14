# Personal Knowledge Base (Personal-KB) MCP Instructions

Personal Knowledge Base quản lý tập trung toàn bộ đặc tả kỹ thuật, ràng buộc phủ định, code mẫu chuẩn và quyết định kiến trúc (`Demo-Core`, `MyNotch`, `Personal-KB`, `AGY-Remote-Hub`, `CyberOS`).

## Hướng dẫn Chọn Công cụ theo Tác vụ

- **Lối tắt Hợp nhất (`query_cognitive_memory`):** Ưu tiên gọi đầu tiên khi bắt đầu tác vụ phức tạp hoặc lập trình.
  - `intent_hint="code"`: Tự động gom trọn gói **Context Triad** (*Spec Contract + Top-3 Negative Constraints + Golden Exemplar*), tiết kiệm >90% token.
  - `intent_hint="architecture"`: Nạp các quyết định kiến trúc dài hạn (**Episodic ADRs** từ `knowledge/adrs/`).
  - `intent_hint="theory"`: Nạp các đoạn trích Spec chính xác kèm neo trích dẫn.
- **Code mẫu chuẩn sản xuất (`recall_exemplar`):** Gọi khi viết code thuộc các mẫu chuẩn như tính lương (`pattern="payroll"`), chấm công (`pattern="timesheet"`), hoặc MCP tool (`pattern="mcp"`).
- **Ràng buộc cấm kỵ (`recall_guardrails`):** Gọi để nạp nhanh Top-3 điều cấm kỹ thuật `[FORBIDDEN]` theo `project` và `topic` trước khi viết code.
- **Đối soát trích dẫn chống ảo giác (`verify_citation`):** Gọi khi cần xác thực nguyên văn câu trích dẫn, công thức tiền tệ/thuế, hoặc quy định nhạy cảm với bản gốc kèm SHA-256 audit hash.
- **Tra cứu chi tiết & Toàn văn:** Dùng `search_knowledge` để tìm kiếm đoạn văn hẹp; dùng `get_spec_content` / `list_specs` để đọc toàn văn tài liệu theo `spec_id`.
- **Nhật ký tiến độ:** Dùng `log_progress` để ghi lại bước làm, cạm bẫy (`gotcha`), quyết định (`decision`); dùng `get_worklog` để đọc lại lịch sử phiên.
- **Cập nhật tri thức:** Khi cập nhật trực tiếp `knowledge/`, thông báo rõ diff cho người dùng và chạy re-ingest. Dùng `propose_knowledge_update` khi cần đưa vào hàng đợi phê duyệt.
