## 1. Mục đích & Bối cảnh (Context & What)
<!-- Nêu ngắn gọn tính năng, bugfix hoặc refactor. Dẫn link Issue / Ticket nếu có. -->
- **Mục tiêu:** 
- **Liên quan:** `Fixes #` hoặc `Refs #`

---

## 2. Phạm vi Tác động & Hợp đồng Thực thi (Execution Scope)
<!-- Kiểm soát chặt chẽ các file và module bị chỉnh sửa, loại trừ side-effect ngoài ý muốn. -->
- **Files chính thay đổi:**
  - `...`
- **Ràng buộc phủ định đã tuân thủ (Negative Constraints):**
  - [x] Không làm vỡ backward-compatibility của các Public API hiện hữu.
  - [x] Không chèn hardcode secret, credentials hoặc URL môi trường.
  - [x] Không sửa trực tiếp các bảng/kỳ dữ liệu đã chốt trạng thái (Locked/Audited).

---

## 3. Bằng chứng Thực nghiệm Bắt buộc (Empirical Verification Proof)
> [!IMPORTANT]
> **Nguyên tắc "Zero Paper Approval":** Tuyệt đối cấm nghiệm thu trên giấy hoặc chỉ ghi "Đã test OK". Mọi thay đổi logic bắt buộc phải có log chạy thực tế hoặc ảnh chụp màn hình kiểm chứng.

### A. Kết quả Automated Tests
```bash
# Lệnh chạy test và output thực tế (Exit code 0, số lượng tests passed)
```

### B. Kiểm chứng API & Trạng thái Database (End-to-End Side-Effect)
<!-- Minh chứng gọi API thật và sự thay đổi dữ liệu trong Database -->
<details>
<summary>Xem chi tiết Request / Response & DB State Diff</summary>

**1. cURL Request & Response:**
```bash
# cURL invocation & HTTP response status/body
```

**2. Database State Before & After:**
```sql
-- Query kiểm tra dữ liệu trước và sau khi gọi API
```
</details>

---

## 4. Danh mục Tự kiểm tra Trước khi Merge (Self-Checklist)
- [ ] Mã nguồn tuân thủ coding conventions của dự án, không có warning/lint lỗi.
- [ ] Không có file log, backup (`.bak`, `.tmp`), hoặc console debug rác.
- [ ] Logic nghiệp vụ thay đổi đã được cập nhật đồng bộ vào tài liệu đặc tả (`docs/` hoặc `knowledge/`).
