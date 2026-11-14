---
id: PKB-04
title: Quy trình Quản trị Tri thức & Phê duyệt Đề xuất (Knowledge Governance & Approvals)
project: Personal-KB
owner: Ryan Truong
status: active
tags: [governance, approval, proposals, occ, human-gate, pkb]
---

# 1. Triết Lý Thiết Kế: Auto-Approval by Default & Conflict-Gated Human Fallback

Trong hệ thống Personal-KB, tài liệu đặc tả là **Chân lý Duy nhất (Source of Truth)**. Để đảm bảo kho tri thức luôn phản ánh chính xác nhất hiện trạng hệ thống và không làm gián đoạn dòng chảy thông tin giữa các phiên làm việc của AI Agent:

1. **Tự động Phê duyệt Mặc định (Auto-Approved by Default):**
   - Mọi đề xuất tri thức hợp lệ (bổ sung bài học, cạm bẫy kỹ thuật Gotchas, quyết định kiến trúc ADRs, mã mẫu Exemplars) được hệ thống **TỰ ĐỘNG PHÊ DUYỆT (`auto_approve=True`, `status: APPROVED`)** và áp dụng ngay lập tức vào file Markdown gốc.
   - Xóa bỏ triệt để tình trạng ứ đọng đề xuất ở trạng thái `PENDING` gây cô lập tri thức khỏi pipeline Vector RAG (đối soát bài học tại `PKB-GOTCHAS.md`).
2. **Quyền Đọc & Ghi Trực tiếp của Agent:**
   - AI Agent được trao quyền cập nhật tri thức trực tiếp (cả qua MCP tool `propose_knowledge_update` lẫn chỉnh sửa trực tiếp file Markdown trong `knowledge/` tuân thủ đúng chuẩn frontmatter).
3. **Cổng Kiểm Soát Con Người Phòng Vệ (Conflict-Gated Human Gatekeeper):**
   - Trạng thái `PENDING` chỉ được kích hoạt duy nhất như một cơ chế phòng vệ an toàn khi hệ thống phát hiện đề xuất có nguy cơ phá vỡ hoặc xung đột với các Ràng buộc Phủ định (`conflict_detected=True`).
   - Khi đó, đề xuất sẽ được giữ lại trong hàng đợi `/approvals` chờ Human Gatekeeper xem xét, đối soát và quyết định duyệt cưỡng chế (`--force`) hoặc từ chối (`reject`).

---

# 2. Cơ Cấu Lưu Trữ Staging File-Based (Proposal Store)

Đề xuất cập nhật được lưu dưới dạng file JSON độc lập tại:
```
knowledge/proposals/PROP-{timestamp}-{hash}.json
```

### Cấu trúc bản ghi `KbProposal`:
- `id`: Mã định danh đề xuất (ví dụ: `PROP-20261019183946-7589dc`).
- `spec_id`: Mã tài liệu chịu ảnh hưởng (ví dụ: `PKB-01`).
- `title`: Tiêu đề tóm tắt nội dung đề xuất.
- `action`: Loại hành động (`UPDATE_SECTION` | `CREATE_DOCUMENT` | `REPLACE_DOCUMENT`).
- `section`: Tên tiêu đề mục (heading) cần bổ sung hoặc cập nhật.
- `proposed_content`: Nội dung Markdown mới đề xuất.
- `rationale`: Căn cứ / Lý do giải trình việc đề xuất.
- `base_hash`: SHA-256 hash của tài liệu gốc tại thời điểm tạo đề xuất (phục vụ OCC).
- `status`: Trạng thái (`APPROVED` theo mặc định, `PENDING` khi phát hiện xung đột, `REJECTED`).
- `conflict_detected`: Cờ boolean đánh dấu đề xuất có vi phạm Negative Constraints hay không.
- `conflict_rule_id`: Mã điều cấm bị vi phạm nếu có xung đột.
- `created_at`: Thời điểm tạo (ISO 8601 UTC).
- `reviewed_at`: Thời điểm duyệt hoặc từ chối (trùng `created_at` nếu tự động duyệt).
- `reviewed_by`: Tên người thực hiện duyệt (`system:auto-approval` hoặc tên Human Gatekeeper).
- `review_note`: Ghi chú phản hồi khi từ chối đề xuất hoặc giải trình duyệt.

---

# 3. Bảo Vệ An Toàn & Optimistic Concurrency Control (OCC)

### 3.1 Chống Tấn Công Path Traversal
Hàm `resolve_spec_path` kiểm tra bắt buộc regex `^[A-Za-z0-9_.-]{1,64}$` và xác thực đường dẫn tuyệt đối phải nằm trong thư mục `knowledge/`. Mọi nỗ lực truy cập vượt ra ngoài thư mục gốc (`../`) đều bị chặn và ném ngoại lệ bảo mật `ValueError`.

### 3.2 Cơ Chế Kiểm Soát Đồng Thời Lạc Quan (OCC)
- Khi đề xuất được tạo, hệ thống tính toán SHA-256 hash của file spec gốc và lưu vào `base_hash`.
- Khi người dùng bấm Phê duyệt (Approve) thủ công, hệ thống kiểm tra lại SHA-256 hash hiện tại của file spec.
- Nếu hash hiện tại khác `base_hash`, điều đó có nghĩa là tài liệu đã bị ai đó chỉnh sửa trong thời gian chờ duyệt. Hệ thống sẽ chặn thao tác và cảnh báo `ProposalConflictError (HTTP 409 Conflict)` để tránh ghi đè mất dữ liệu (Lost Update).

---

# 4. Vòng Đời Đề Xuất & Tự Động Re-ingestion

```
[ AI Agent / User ]
       |
       v (propose_knowledge_update)
       |
       +---> [ Kiểm tra Xung đột Quy tắc Cấm? ]
                   |
     +-------------+-------------+
     | Không (Mặc định 99%)      | Có vi phạm Negative Constraint
     v                           v
+-----------------------+   +-----------------------+
| Trạng thái: APPROVED  |   |  Trạng thái: PENDING  | <--- Hàng đợi /approvals
+-----------------------+   +-----------------------+
| 1. Ghi đè Markdown    |                |
| 2. Đóng chunk cũ      |      +---------+---------+
| 3. Nhúng chunk mới    |      |                   |
| 4. Update DocumentStore     v                   v
+-----------------------+  (Duyệt --force)    (Từ chối / Reject)
                               |                   |
                               v                   v
                    +-------------------+ +-------------------+
                    | Trạng thái:       | | Trạng thái:       |
                    | APPROVED          | | REJECTED          |
                    +-------------------+ +-------------------+
```

### Cơ chế Tự động Áp dụng và Re-ingestion:
Khi đề xuất được Phê duyệt (tự động hoặc qua Human Gate), hàm `store.approve()` tự động gọi bộ máy `ingestion`:
- Cập nhật toàn văn tài liệu vào `DocumentStore` và ghi file Markdown trên đĩa.
- Đóng các chunk cũ liên quan bằng cách gán `valid_to = now()`.
- Sinh vector embedding cho nội dung mới và nạp vào pgvector ngay lập tức.
- **Kết quả:** Người dùng và AI Agent ở các phiên làm việc tiếp theo có thể truy vấn và trích xuất thông tin mới tức thì mà không cần khởi động lại máy chủ.
