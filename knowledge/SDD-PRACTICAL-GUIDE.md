---
id: SDD-PRACTICAL-GUIDE
title: "Hướng dẫn Áp dụng SDD Thực chiến: Bounded Contract & Empirical Proof"
project: Personal-KB
memory_tier: foundational
status: APPROVED
author: "Ryan Truong & Senior Architect"
version: "1.0.0"
last_updated: "2026-10-31"
tags: [sdd, methodology, developer-ergonomics, ai-guardrails, quality-gate]
---

# Hướng dẫn Áp dụng SDD Thực chiến: Bounded Contract & Empirical Proof

Tài liệu này đúc kết và chuẩn hoá 2 pattern giá trị nhất từ mô hình **Spec-Driven Development (SDD)** của CyberOS, được tinh gọn hóa để loại bỏ toàn bộ các thủ tục hành chính cồng kềnh, tập trung 100% vào **công thái học lập trình (Developer Ergonomics)** và **kiểm soát AI an toàn** trong công việc hàng ngày.

---

## 1. Bối cảnh & Triết lý Tinh gọn

Mô hình SDD nguyên bản (với hàng trăm quyết định DEC, 2 cổng duyệt con người kéo dài, hệ thống sổ cái bất biến) được thiết kế cho các hệ thống an ninh cực đoan hoặc chạy tự động hóa hoàn toàn bằng AI. Nếu áp đặt nguyên xi lên đội ngũ kỹ sư thực tế, nó sẽ gây ra ma sát lớn (friction) và làm triệt tiêu vận tốc phát triển (velocity).

Tuy nhiên, 2 nguyên lý kỹ thuật cốt lõi sau đây mang lại giá trị vượt trội ngay lập tức khi được đưa vào dự án:

```
+-----------------------------------------------------------------------------------+
|                         QUY TRÌNH 2 CHỐT CHẶN TINH GỌN                            |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  [ ĐẦU VÀO: Bounded Execution Contract ]   --->   [ ĐẦU RA: Empirical Proof ]     |
|  - Khóa chặt danh sách file được sửa              - Cấm "nghiệm thu trên giấy"    |
|  - Thiết lập 3 điều cấm kỵ (Negative)             - Bắt buộc log test thật        |
|  - Phê duyệt kế hoạch trước khi code              - cURL & DB state diff thực tế  |
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

---

## 2. Pattern 1: Bounded Execution Contract (Hợp đồng Thực thi Giới hạn)

### 2.1. Vấn đề giải quyết
- **Khi làm việc với AI:** AI có xu hướng "sửa quá tay" (over-engineering), tự ý refactor các module không liên quan, xóa nhầm comment nghiệp vụ hoặc cài thêm thư viện thừa thãi.
- **Khi dev người làm việc:** Kỹ sư làm tính năng A nhưng tiện tay chỉnh sửa dạo tính năng B, gây ra lỗi hồi quy (regression bugs) khó phát hiện.

### 2.2. Cơ chế 3 Chốt chặn (The 3-Point Contract)
Trước khi bất kỳ dòng code nào được viết hoặc chỉnh sửa, lập trình viên (hoặc AI) bắt buộc phải xác lập một hợp đồng ngắn gọn:

1. **`ALLOWED FILES` (Danh sách file được phép chỉnh sửa):**
   - Chỉ định danh sách cụ thể (Whitelist). Tuyệt đối không chạm vào bất kỳ file nào nằm ngoài danh sách.
2. **`NEGATIVE CONSTRAINTS` (Ràng buộc phủ định - Điều cấm kỵ):**
   - Nêu rõ 2–3 điều cấm bất khả xâm phạm của domain nghiệp vụ.
   - *Ví dụ:* Không dùng kiểu `float`/`double` cho tiền tệ; Không hard delete nhân sự; Không sửa kỳ công đã `LOCKED`; Không phá vỡ schema API cũ.
3. **`EXECUTION STEPS` (Các bước thực hiện tuần tự):**
   - Liệt kê tối đa 3–5 bước triển khai logic mạch lạc.

### 2.3. Mẫu Prompt Chuẩn khi Giao Việc cho AI (Copy-Ready)
Sử dụng prompt sau khi bắt đầu yêu cầu AI (Cursor / Claude / Copilot / Antigravity) làm bất kỳ task nào:

```markdown
Trước khi viết bất kỳ dòng mã nào, hãy khảo sát codebase và xuất ra một EXECUTION CONTRACT theo định dạng sau để tôi phê duyệt:

1. ALLOWED FILES: Liệt kê chính xác các file bạn dự kiến tạo mới hoặc chỉnh sửa (không được sửa file ngoài danh mục này).
2. NEGATIVE CONSTRAINTS: 3 điều bạn TUYỆT ĐỐI KHÔNG ĐƯỢC PHÉP LÀM đối với tác vụ này (để bảo vệ an toàn dữ liệu và kiến trúc).
3. STEP-BY-STEP: Tối đa 4 bước triển khai logic chính.

Chờ tôi phản hồi "APPROVED" thì mới được bắt đầu viết code!
```

---

## 3. Pattern 2: Empirical Proof over Assumed Passing (Bằng chứng Thực nghiệm)

### 3.1. Vấn đề giải quyết
- **Ảo tưởng thành công (Assumed Passing):** Dev/AI tuyên bố *"Đã xong"*, *"Code chạy tốt"* chỉ vì trình biên dịch không báo lỗi cú pháp hoặc server trả về HTTP 200, nhưng thực tế dữ liệu không được ghi vào DB hoặc nghiệp vụ tính toán sai lệch.
- **Zero Paper Approval:** Không bao giờ chấp nhận bất kỳ lời khẳng định chất lượng nào nếu không kèm theo bằng chứng máy tính thực thi (Execution Proof).

### 3.2. Quy chuẩn 3 Tầng Bằng chứng
Mọi Pull Request hoặc báo cáo hoàn thành tính năng bắt buộc phải đính kèm tối thiểu 2 trong 3 tầng bằng chứng sau:

| Tầng Bằng chứng | Yêu cầu Kỹ thuật | Ví dụ Minh họa |
| :--- | :--- | :--- |
| **1. Automated Test Output** | Lệnh test chạy thực tế trên terminal kèm exit code `0` và số lượng test passed. | `dotnet test --filter Category=Payroll`<br>`Passed: 14, Failed: 0` |
| **2. Request / Response Log** | Lệnh `cURL` hoặc HTTP client gọi vào endpoint thật kèm mã HTTP và body trả về. | `curl -X POST /api/v1/leaves/approve`<br>`HTTP/1.1 200 OK {"status": "APPROVED"}` |
| **3. Database State Diff** | Query kiểm tra trạng thái bảng trước và sau khi gọi lệnh (End-to-End Side-Effect). | `SELECT status, balance FROM leaves;`<br>-> Chứng minh `balance` đã bị trừ đúng 1 ngày. |

---

## 4. Hướng dẫn Tích hợp vào Dự án

### 4.1. Cài đặt Pull Request Template
Sao chép tệp mẫu `pull_request_template.md` vào thư mục gốc của repository:
```bash
cp /Users/ryantruong/Project/personal-kb/knowledge/templates/pull_request_template.md .github/pull_request_template.md
```

### 4.2. Quy ước Review của Tech Lead
- **Fail-Closed Gate:** Bất kỳ PR nào thiếu phần **`## 3. Bằng chứng Thực nghiệm Bắt buộc`** sẽ bị từ chối duyệt (`REVISE`) ngay lập tức mà không cần đọc chi tiết code diff.
- Quy định này giúp Tech Lead tiết kiệm 70% thời gian review code, vì chỉ cần nhìn vào log kiểm thử và DB state diff là biết tính năng đã thực sự chạy đúng nghiệp vụ hay chưa.

---

## 5. Ví dụ Áp dụng Thực chiến (Case Studies)

### 5.1. Ví dụ trên .NET / C# (Hệ thống Demo-Core)
**Tác vụ:** Cập nhật tính năng duyệt đơn xin nghỉ phép (`ApproveLeaveRequest`).

```markdown
### EXECUTION CONTRACT:
- ALLOWED FILES:
  - `src/HRM.Application/Leaves/Commands/ApproveLeaveCommand.cs`
  - `src/HRM.Infrastructure/Persistence/Repositories/LeaveRepository.cs`
  - `tests/HRM.UnitTests/Leaves/ApproveLeaveTests.cs`
- NEGATIVE CONSTRAINTS:
  - CẤM duyệt đơn khi số ngày phép tồn (`AnnualLeaveBalance`) < số ngày xin nghỉ.
  - CẤM sửa trực tiếp các đơn đã có trạng thái `CANCELLED` hoặc `REJECTED`.
  - CẤM dùng lệnh SQL raw bypass Entity Framework change tracking.
- STEPS:
  1. Thêm validation check số dư phép trong Command Handler.
  2. Cập nhật trạng thái đơn thành `APPROVED` và trừ `AnnualLeaveBalance` trong transaction.
  3. Viết unit test kiểm tra trường hợp hợp lệ và trường hợp thiếu số dư phép.

### EMPIRICAL PROOF (Đính kèm PR):
1. Unit test:
   `dotnet test --filter FullyQualifiedName~ApproveLeaveTests` -> `Passed! 4 tests`
2. DB State Diff:
   - Trước: `user_id = 10, balance = 12, leave_status = PENDING`
   - Sau: `user_id = 10, balance = 10, leave_status = APPROVED`
```

### 5.2. Ví dụ trên Python / FastAPI (Hệ thống Personal-KB)
**Tác vụ:** Sửa lỗi Re-ingest tài liệu sau khi phê duyệt Proposal (`approve_proposal`).

```markdown
### EXECUTION CONTRACT:
- ALLOWED FILES:
  - `ai/backend/services/retrieval.py`
  - `ai/backend/api/proposals.py`
- NEGATIVE CONSTRAINTS:
  - CẤM sửa đổi cấu trúc bảng `proposals` trong database.
  - CẤM gọi mô hình embedding cloud từ bên ngoài (bắt buộc dùng Local Ollama).
- STEPS:
  1. Expose `@property def embedder` trong class `HybridRetriever`.
  2. Bổ sung kiểm tra an toàn `getattr(retriever, "embedder", None)`.
  3. Chạy test suite `test_proposals.py`.

### EMPIRICAL PROOF (Đính kèm PR):
1. Test suite:
   `pytest ai/backend/tests/test_proposals.py -v` -> `5 passed in 1.42s`
2. API & Cache Check:
   - Gọi `POST /api/v1/proposals/PRP-01/approve` -> `HTTP 200 OK`
   - Log kiểm tra: `Re-indexing completed: 15 chunks updated in pgvector.`
```

---

## 6. Tổng kết Quy chuẩn

| Nguyên tắc | Mô tả ngắn | Giá trị đạt được |
| :--- | :--- | :--- |
| **Contract trước Code** | Không viết code khi chưa có file scope và điều cấm kỵ | Triệt tiêu lỗi lan man, giữ vững kiến trúc |
| **Bằng chứng trên Lời nói** | Mọi PR bắt buộc có log test thật và DB diff | Loại bỏ hoàn toàn lỗi nghiệm thu ảo |
| **Tài liệu sống cùng PR** | Logic đổi thì cập nhật spec ngay trong PR | Xóa sạch Spec Debt, bảo trì hệ thống lâu dài |
