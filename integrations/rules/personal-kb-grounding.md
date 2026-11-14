<!-- BEGIN PERSONAL-KB GROUNDING RULES -->
## Quy tắc Tra cứu Tri thức & Trí nhớ Hệ thống (Personal Knowledge Base Grounding)

Toàn bộ thông số kiến trúc, quy trình nghiệp vụ và logic hệ thống (`Demo-Core`, `MyNotch`, `Personal-KB`, `AGY-Remote-Hub`, `CyberOS`) được quản lý tập trung tại kho tri thức **Personal-KB** (kết nối qua MCP Server `personal-kb` hoặc REST API `http://localhost:8000/api/v1/agent/tools/search`).

1. **Nguyên tắc Chân lý Duy nhất (Spec-as-Truth & Zero-Hallucination):**
   - TUYỆT ĐỐI KHÔNG tự bịa ra công thức tính lương, trạng thái đơn từ, mã lỗi API hoặc quy định hệ thống từ kiến thức chung của LLM.
   - MỌI khẳng định kỹ thuật/nghiệp vụ bắt buộc phải được đối soát từ nội dung tài liệu trả về. Nếu kho tri thức chưa có, BẮT BUỘC tuyên bố rõ: *"Hệ thống chưa có Spec quy định nội dung này"*, không được phỏng đoán.
2. **Bộ Định tuyến Nhận thức Hợp nhất & Tra cứu Trước khi Trả lời (`query_cognitive_memory` & Retrieve-Before-Answering):**
   - **Ưu tiên số 1 — All-in-One Router (`query_cognitive_memory`):** Khi bắt đầu một tác vụ tổng hợp (viết code, thiết kế kiến trúc, hoặc tra cứu nghiệp vụ), ưu tiên gọi `query_cognitive_memory(query="...", project="...", intent_hint="auto|code|architecture|theory")` để lấy trọn gói ngữ cảnh tối ưu chỉ trong 1 lượt gọi:
     - `intent_hint="code"`: Tự động đóng gói **Context Triad** (*Spec Contract + Top-3 Negative Constraints + Golden Exemplar*), tiết kiệm >90% token so với đọc nguyên file Spec.
     - `intent_hint="architecture"`: Tự động nạp các quyết định kiến trúc dài hạn (**Episodic ADRs** từ `knowledge/adrs/`).
     - `intent_hint="theory"`: Nạp các đoạn trích Spec chính xác kèm neo trích dẫn.
   - **Tra cứu chi tiết (`search_knowledge`, `get_spec_content`, `list_specs`):** Dùng khi cần tìm kiếm hẹp hoặc đọc nguyên văn 100% một tài liệu theo `spec_id`. Các mã dự án chính: `Demo-Core`, `MyNotch`, `Personal-KB`, `AGY-Remote-Hub`, `CyberOS`.
3. **Bắt buộc Trích dẫn & Đối soát Chống Ảo giác (`verify_citation` & Citation Mandate):**
   - Mọi câu trả lời nghiệp vụ phải kèm mã Spec ID ở cuối câu hoặc đoạn (ví dụ: `[HR-M04]`, `[HR-M01]`, `[PKB-01]`, `[ADR-001]`).
   - **Khi nào BẮT BUỘC gọi `verify_citation(spec_id="...", quote="...")`:**
     - Khi trích dẫn trực tiếp nguyên văn quy định, hệ số tiền tệ/thuế/bảo hiểm, công thức tính toán hoặc điều khoản ràng buộc nhạy cảm.
     - Khi cần bằng chứng kiểm toán (Audit Trail kèm `section_heading` và `SHA-256 content_hash`) trong pha Review/Audit hoặc khi đối soát nghi ngờ sai lệch giữa code và Spec.
4. **Quyền Cập nhật Tri thức Trực tiếp & Thông báo Sau (Direct Knowledge Update & Post-Notification):**
   - AI được toàn quyền đọc (`query_cognitive_memory`, `search_knowledge`, `get_spec_content`, `list_specs`, `recall_guardrails`, `recall_exemplar`, `verify_citation`).
   - **Cho phép sửa trực tiếp `knowledge/` + Thông báo sau:** Khi phát hiện thông tin mới cần lưu trữ, đồng bộ kiến trúc/ADR/Gotchas/Exemplar hoặc khi người dùng yêu cầu cập nhật tài liệu, AI **ĐƯỢC PHÉP chỉnh sửa hoặc tạo mới trực tiếp** file Markdown trong `knowledge/` (đảm bảo giữ đúng chuẩn YAML frontmatter `id`, `title`, `project`, `status`, `last_updated` và không làm mất lịch sử/nội dung hợp lệ), sau đó **BẮT BUỘC thông báo rõ cho người dùng** ở cuối câu trả lời (nêu rõ đường dẫn file đã sửa/tạo, mã Spec ID và tóm tắt nội dung thay đổi, kèm nhắc chạy re-ingest nếu cần).
   - **Khi nào dùng `propose_knowledge_update`:** Chỉ dùng khi người dùng chủ động yêu cầu *"tạo proposal chờ duyệt"* hoặc khi thay đổi chính sách nghiệp vụ còn gây tranh cãi cần đưa vào hàng đợi `/approvals` để thảo luận trước.
5. **Quy tắc Ràng buộc Phủ định & Code Mẫu Chuẩn Sản Xuất (`recall_guardrails` & `recall_exemplar`):**
   - **Kiểm tra điều cấm (`recall_guardrails`):** TRƯỚC KHI viết mã nguồn, thiết kế database, hoặc triển khai hàm tính toán (nếu chưa gọi `query_cognitive_memory` với `intent_hint="code"`), BẮT BUỘC gọi `recall_guardrails(project="...", topic="...")` và tuân thủ 100% các điều cấm gắn nhãn `[FORBIDDEN]` (ví dụ: cấm `float` cho tiền tệ, cấm hardcode hệ số luật định, cấm hard delete nhân sự, cấm sửa trực tiếp kỳ công đã `LOCKED`).
   - **Tham chiếu Golden Few-Shot Code (`recall_exemplar`):** Khi triển khai code thuộc các mẫu chuẩn đã có trong kho (như tính lương `pattern="payroll"` -> `HR-EX-001`, điều chỉnh công khóa sổ `pattern="timesheet"` -> `HR-EX-002`, viết MCP tool `pattern="mcp"` -> `PKB-EX-001`), BẮT BUỘC gọi `recall_exemplar(project="...", pattern="...")` để đối chiếu cấu trúc type hints, exception boundary và chuẩn xử lý Decimal/Audit Trail trước khi viết code.
   - Khi hoàn thành một pattern mẫu mực mới có giá trị tái sử dụng cao, chủ động đóng gói thành file exemplar mới trong `knowledge/<Project>/exemplars/<PREFIX>-EX-00X.md` và báo cho người dùng.
6. **Quản trị Quyết định Kiến trúc Dài hạn — Phân hệ ADRs (`knowledge/adrs/`):**
   - **Tra cứu trước khi thiết kế/refactor lớn:** Khi thiết kế kiến trúc, thay đổi schema, chọn database/vector store hoặc thay đổi giao thức hệ thống, BẮT BUỘC tra cứu các ADR hiện hành (`query_cognitive_memory(..., intent_hint="architecture")` hoặc đọc `ADR-001`, `ADR-002`, `ADR-003`...) để không phá vỡ các quyết định nền tảng đã chốt.
   - **Ghi nhận ADR mới:** Khi chốt một quyết định kiến trúc quan trọng (có đánh đổi giữa các phương án A/B, thay đổi hạ tầng, giao thức hoặc cơ chế bảo mật), Agent chủ động tạo hoặc cập nhật file `knowledge/adrs/ADR-00X.md` (gồm: Frontmatter `memory_tier: episodic`, `item_type: adr`, `status: ACCEPTED`, `Context`, `Decision`, `Rationale`, `Consequences`) và thông báo cho người dùng. Nếu quyết định mới thay thế ADR cũ, cập nhật `status: SUPERSEDED` và `superseded_by` ở ADR cũ.
7. **Quy tắc Chủ động Cập nhật Gotchas & Guardrails (Proactive Gotcha-to-Guardrail Pipeline):**
   - Worklog (`log_progress` với `kind="gotcha"`) chỉ là nhật ký cá nhân tạm thời của phiên làm việc.
   - Khi gỡ xong một lỗi kiến trúc/hạ tầng nghiêm trọng (RCA) hoặc phát hiện cạm bẫy mới (desync tài khoản, deadlock, mất token, bốc nhầm session, vỡ layout đa viewport):
     - Agent có thể **bổ sung trực tiếp** mục `- **[FORBIDDEN] [NC-...]` hoặc `[CAUTION]` vào file `[PROJECT]-GOTCHAS.md` trong `knowledge/` rồi thông báo rõ cho người dùng ở cuối câu trả lời (hoặc hỏi người dùng nếu cạm bẫy cần xác nhận thêm).
8. **Quy ước Phê duyệt Proposal (Human-Delegated Approval Protocol — khi dùng hàng đợi `/approvals`):**
   - Với các đề xuất đang nằm trong hàng đợi Proposal (`scripts/manage_proposals.py`), AI chỉ thực thi duyệt/từ chối khi có lệnh từ người dùng:
     - `Duyệt proposal <id>` / `Approve proposal <id>`: Chạy `python3 scripts/manage_proposals.py show <id>` kiểm tra xung đột; nếu an toàn, chạy `python3 scripts/manage_proposals.py approve <id> --reviewer "Ryan Truong"`.
     - `Review proposal <id>`: Đọc diff, đối soát quy chuẩn và tư vấn.
     - `Từ chối proposal <id> vì <lý do>`: Chạy `python3 scripts/manage_proposals.py reject <id> --note "<lý do>"`.
     - `Xem danh sách proposal`: Chạy `python3 scripts/manage_proposals.py list`.
   - Nếu đề xuất bị cờ xung đột (`conflict_detected=True`), BẮT BUỘC cảnh báo và chỉ duyệt khi có từ khóa `ép buộc` hoặc `--force`.
9. **Worklog (vùng AI tự ghi tiến độ phiên):**
   - Worklog được ghi thẳng qua MCP tool `log_progress`, KHÔNG qua Proposal.
   - Gọi `log_progress` khi xong một bước đáng kể, khi ra quyết định, khi gặp cạm bẫy, và trước khi kết thúc/bàn giao phiên làm việc. Đọc lại worklog bằng `get_worklog`.
   - Ở lượt đầu của hội thoại mới trong một repo, nếu ngữ cảnh chưa có dòng `PROJECT BRIEF`, chạy `/usr/bin/python3 ~/Project/personal-kb/scripts/project_brief.py --runtime agy --cwd "$PWD"` và đọc kết quả trước khi làm.
<!-- END PERSONAL-KB GROUNDING RULES -->
