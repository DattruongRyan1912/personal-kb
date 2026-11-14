---
id: PKB-03
title: Giao thức Tích hợp AI Agent & Model Context Protocol (MCP)
project: Personal-KB
owner: Ryan Truong
status: active
tags: [agent, mcp, protocol, tooling, automation, pkb]
---

# 1. Giới thiệu Model Context Protocol (MCP) cho Personal-KB

Personal-KB tích hợp giao thức mở **Model Context Protocol (MCP 2.x)** của Anthropic, cho phép mọi AI Agent (như Claude Desktop, Cursor IDE, Antigravity CLI, Zed, v.v.) kết nối trực tiếp vào kho tri thức cá nhân mà không cần phát triển thêm plugin tùy biến.

Tên MCP Server chuẩn: `personal-kb`

---

# 2. Danh Sách Các Tools Cung Cấp Cho Agent

MCP Server của Personal-KB expose 5 công cụ chuẩn:

### 1. `search_knowledge`
- **Mục đích:** Tìm kiếm ngữ nghĩa trong kho tri thức khi agent cần tìm thông tin về luồng xử lý hoặc mã tài liệu.
- **Tham số:** `query: str` (câu truy vấn ngắn gọn), `limit: int = 5` (số lượng kết quả tối đa).
- **Đầu ra:** Các trích đoạn có độ tương đồng cao nhất kèm mã Spec ID, tiêu đề mục và điểm score.

### 2. `get_spec_content`
- **Mục đích:** Đọc nguyên văn 100% nội dung (code, bảng biểu, quy tắc) của một spec cụ thể.
- **Tham số:** `spec_id: str` (ví dụ: `PKB-01`, `PKB-02`).
- **Đầu ra:** Toàn bộ nội dung Markdown của tài liệu.

### 3. `list_specs`
- **Mục đích:** Xem danh mục mã ID, tiêu đề và tác giả của toàn bộ các tài liệu hiện có trong kho.
- **Tham số:** Không có.
- **Đầu ra:** Danh sách các spec kèm metadata tóm tắt.

### 4. `verify_citation`
- **Mục đích:** Đối soát tính xác thực của một đoạn trích dẫn đối chiếu với văn bản gốc trong tài liệu đặc tả.
- **Tham số:** `spec_id: str`, `quote: str` (đoạn trích dẫn cần kiểm chứng).
- **Đầu ra:** Xác nhận thành công (kèm heading mục chứa trích dẫn, trạng thái spec, SHA-256 hash và link deep-link) hoặc cảnh báo ảo giác nếu không tìm thấy trích dẫn.

### 5. `propose_knowledge_update`
- **Mục đích:** Tạo đề xuất cập nhật tri thức khi agent phát hiện thông tin trong spec bị lỗi thời hoặc người dùng cung cấp thông tin mới.
- **Tham số:** `spec_id: str`, `title: str`, `proposed_content: str`, `rationale: str`, `section: str = ""`.
- **Đầu ra:** Mã đề xuất `PROP-YYYYMMDD-XXXXXX` ở trạng thái `PENDING` được gửi lên hệ thống cho con người duyệt tại trang `/approvals`.

---

# 3. Tài Nguyên MCP (MCP Resources)

MCP Server cung cấp URI Scheme:
```
spec://{spec_id}
```
Cho phép AI Agent có thể đọc trực tiếp tài liệu nguyên bản như một file tài nguyên ảo trong ngữ cảnh làm việc.

---

# 4. Hướng Dẫn Cấu Hình Kết Nối Client

### 4.1 Cấu hình cho Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "personal-kb": {
      "command": "/bin/bash",
      "args": ["/Users/ryantruong/Project/personal-kb/scripts/mcp_server.sh"]
    }
  }
}
```

### 4.2 Cấu hình cho Cursor IDE (`.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "personal-kb": {
      "command": "/bin/bash",
      "args": ["/Users/ryantruong/Project/personal-kb/scripts/mcp_server.sh"]
    }
  }
}
```

### 4.3 Chế độ M2M Agent REST API (Tối ưu hóa Token)
Backend cung cấp thêm namespace `/api/v1/agent/*`:
- `POST /api/v1/agent/query`: Trả về JSON thuần `{ "answer": "...", "citations": [...] }`.
- Khi câu hỏi kèm chỉ thị `[CHẾ ĐỘ M2M AGENT - TỐI ƯU TOKEN]`: Agent trả lời bằng bullet points hoặc bảng ngắn gọn, triệt tiêu mở bài/kết luận thừa để tiết kiệm tối đa token context window cho các agent gọi lồng nhau.
