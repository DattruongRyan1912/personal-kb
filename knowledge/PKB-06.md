---
id: PKB-06
title: "Báo Cáo Bàn Giao & Tiến Trình: Active Cognitive Memory Fabric & Quản Trị Tri Thức (Giai Đoạn 1, 2 & 3)"
project: Personal-KB
owner: Ryan Truong
status: active
tags: [handover, cognitive-memory, session-summary, phase1, phase2, phase3, pkb, adr, exemplars, approvals]
version: "2.0.0"
last_updated: "2026-10-24"
---

# PKB-06: Báo Cáo Bàn Giao & Tiến Trình: Active Cognitive Memory Fabric & Quản Trị Tri Thức

> [!IMPORTANT]
> **TÀI LIỆU BÀN GIAO TIẾP NHẬN PHIÊN (SESSION HANDOVER CONTEXT)**  
> Tài liệu này lưu trữ toàn bộ thành tựu kỹ thuật, trạng thái hệ thống và bản thiết kế tiếp nối cho phiên làm việc tiếp theo. Mọi Agent mới khi khởi tạo chỉ cần đọc tài liệu này (`get_spec_content("PKB-06")`) là lập tức nạp đủ 100% ngữ cảnh kiến trúc mà không bị ảo giác.

---

## 1. Bối Cảnh & Đột Phá Kiến Trúc (Executive Summary)

Hệ thống **Personal-KB** đã hoàn thành toàn diện quá trình chuyển đổi từ một kho tài liệu tĩnh (Static Spec Hub) thành **Kho Trí Nhớ Nhận Thức Dài Hạn (Active Cognitive Memory Fabric)** và thiết lập cơ chế **Quản trị Tri thức Human-in-the-loop (Knowledge Governance & Human Gate)**.

### Vấn Đề Cốt Lõi Đã Giải Quyết:
- **Hiện tượng Naive RAG thất bại:** Việc nhồi nhét hàng ngàn dòng tài liệu thô vào prompt khiến Agent bị **Context Bloat** và **Lost-in-the-Middle**, dẫn đến tỷ lệ vi phạm các lỗi cơ bản lên tới 60%.
- **Giải Pháp:** Xây dựng cấu trúc trí nhớ 4 tầng (**Semantic, Episodic, Procedural, Reflective**) kết hợp cơ chế kiểm soát chất lượng nghiêm ngặt:
  - **Reflective Memory:** Ràng buộc phủ định tường minh (`[FORBIDDEN]`) qua công cụ `recall_guardrails`.
  - **Procedural Memory:** Mã nguồn mẫu chuẩn sản xuất qua công cụ `recall_exemplar`.
  - **Episodic Memory:** Hồ sơ quyết định kiến trúc (`knowledge/adrs/`).
  - **Two-Phase Intent Routing:** Tự động điều phối tri thức theo ngữ cảnh truy vấn qua `query_cognitive_memory`.
  - **Semantic Anti-Collision:** Quét xung đột ngữ nghĩa và chặn đứng đề xuất vi phạm cấm kỵ.
  - **Human Gate & OCC:** Quyền phê duyệt duy nhất thuộc về con người, kiểm soát đồng thời lạc quan chống Lost Updates.

---

## 2. Thành Tựu Đã Triển Khai & Kiểm Chứng

### 2.1. Giai Đoạn 1: Reflective Memory & Negative Constraints (Hoàn tất 100%)
- **Hồ sơ Ràng buộc Cấm Kỵ:**
  - `knowledge/Demo-Core/HR-GOTCHAS.md`: 6 phân hệ, 11 điều cấm kỵ cốt tử (`NC-HR-001` đến `NC-HR-050`). Cấm dùng `float`, cấm hardcode hệ số ca đêm 1.3, cấm sửa công khi `status = 'LOCKED'`, cấm Hard Delete nhân viên, cấm âm phép năm.
  - `knowledge/PKB-GOTCHAS.md`: 4 điều cấm an toàn cho Agent (`NC-PKB-001` đến `NC-PKB-011`).
- **Công cụ MCP `recall_guardrails(project, topic, limit=3)`:**
  - Thuật toán Relevance Scoring: Ưu tiên match Section (+15 điểm) và Header (+10 điểm).
  - Áp dụng **Luật Top-3 Hard Limit (< 180 tokens)** để bảo vệ context window.
- **Đo lường Định lượng (CAR Benchmark):**
  - File kiểm thử: `backend/tests/test_car_benchmark.py` (5 Trap Scenarios).
  - Kết quả: **Base Model CAR = 0.0% $\rightarrow$ Guarded CAR = 100.0%**.

### 2.2. Giai Đoạn 2: Golden Exemplars, Episodic ADRs & Tombstone (Hoàn tất 100%)
- **Mã Nguồn Mẫu Chuẩn Sản Xuất (Golden Few-shot Exemplars):**
  - `knowledge/Demo-Core/exemplars/HR-EX-001.md`: Chuẩn mực tính lương HR-M04 (Decimal, ROUND_HALF_UP, tham số động, lũy tiến thuế TNCN 7 bậc, kiểm tra Net Pay Zero-Tolerance).
  - `knowledge/Demo-Core/exemplars/HR-EX-002.md`: Chuẩn mực điều chỉnh công HR-M02 sau khi kỳ công đã LOCKED (tạo ticket `timesheet_adjustments`, audit trail).
  - `knowledge/Personal-KB/exemplars/PKB-EX-001.md`: Chuẩn mực MCP Tool (logging `sys.stderr`, exception boundary).
- **Hồ Sơ Quyết Định Kiến Trúc (ADRs):**
  - `knowledge/adrs/ADR-001.md`: 1 Collection vector duy nhất + Hierarchical Payload Filter.
  - `knowledge/adrs/ADR-002.md`: Tách biệt Giao thức kép (MCP stdio vs REST SSE).
  - `knowledge/adrs/ADR-003.md`: Ưu tiên Ràng buộc phủ định (Reflective Memory) đạt CAR 100%.
- **Công cụ MCP `recall_exemplar(project, pattern)`:** Bóc tách trực tiếp khối code nguyên vẹn, loại bỏ văn phong giải thích rườm rà.
- **Vòng Đời Tombstone (Triple-Lock Safety):**
  - Bổ sung `tombstone_source` vào `QdrantVectorStore` và `supersedes_spec_id` vào `KbProposal`.
  - Bộ lọc `validity_filter` trong Qdrant tự động loại bỏ toàn bộ chunk đã tombstone khỏi vector search.

### 2.3. Giai Đoạn 3: Two-Phase Cognitive Router, Anti-Collision & Semantic Cache (Hoàn tất 100%)
- **Two-Phase Intent-Gated Cognitive Router (`backend/personal_kb/services/cognitive_router.py`):**
  - Phân loại ngữ cảnh siêu nhẹ (Regex + Heuristic Matching):
    - *Intent A (Theory / Tra cứu quy định):* Tự động lọc và inject Spec Chunks chuẩn xác.
    - *Intent B (Code Gen / Triển khai mã nguồn):* Tự động gói trọn bộ: **Spec Contract + Top-3 Negative Constraints + Golden Exemplar**.
    - *Intent C (Architecture / Thiết kế kiến trúc):* Tự động inject **Episodic ADRs**.
  - Tích hợp công cụ MCP thứ 8: `query_cognitive_memory(query: str, project: str = "Demo-Core", intent_hint: str = "auto")`.
- **Semantic Anti-Collision Engine (`backend/personal_kb/services/anti_collision.py`):**
  - Tự động phát hiện xung đột khi Agent tạo đề xuất qua `propose_knowledge_update`.
  - Gắn cờ `conflict_detected: true`, `conflict_rule_id`, `conflict_reason`.
  - **Hard-Block on Approval:** Chặn đứng việc phê duyệt đề xuất vi phạm cấm kỵ (`ProposalConflictError`) trừ khi người dùng chỉ định rõ cờ `force=True`.
- **Multi-tenant Semantic Cache (`backend/personal_kb/services/semantic_cache.py`):**
  - Bộ nhớ đệm ngữ nghĩa đa dự án dựa trên vector similarity.
  - Tự động vô hiệu hóa cache theo từng dự án qua hàm `bump_version(project_id)` mỗi khi có proposal được duyệt.
- **Hạ Tầng PostgreSQL pgvector & Data Hub:**
  - `pg_vector_store.py`, `pg_document_store.py`, `schema.sql` hoàn thiện schema lưu trữ và hybrid search (RRF).
  - Data Hub API (`backend/personal_kb/api/data_hub.py`) phục vụ phân tích dung lượng, phân bổ chunk theo project.

### 2.4. Quản Trị Phê Duyệt Tri Thức & Giao Thức Ủy Quyền (Hoàn tất 100%)
- **Giao Diện Phê Duyệt & Quản Trị (/approvals & /data):**
  - Portal Next.js tối giản theo phong cách Linear/Dark Zinc 950 (`#09090b`), viền hairline 1px `#27272a`.
  - Dashboard thống kê 4 chỉ số (Tổng đề xuất, Chờ duyệt, Đã duyệt, Đã từ chối).
  - Xem diff Markdown, xem Rationale, cảnh báo Conflict Warning Banner, phê duyệt 1-chạm hoặc từ chối kèm lý do.
- **CLI Bridge Runner (`scripts/manage_proposals.py`):**
  - Tự động chuyển tiếp môi trường sang `backend/.venv/bin/python` (`os.execv`).
  - Hỗ trợ đầy đủ các lệnh: `list`, `show`, `approve`, `reject`.
  - Hỗ trợ chế độ kép: Online (gọi API backend kèm dev token và tự động re-ingest) và Offline (patch trực tiếp Markdown spec và cập nhật JSON proposal).
- **Quy Chuẩn Ra Lệnh Ngắn Gọn (Human-Delegated Approval Protocol):**
  - Đồng bộ quy tắc vào `~/.agents/GLOBAL.md` và `integrations/rules/personal-kb-grounding.md`.
  - Tài liệu bàn giao chuẩn HTML: `docs/KB_APPROVAL_COMMAND_SPEC.html`.
  - Người dùng có thể ra lệnh bằng văn phong tự nhiên: *"Duyệt proposal [ID]"*, *"Review proposal [ID]"*, *"Từ chối proposal [ID] vì [lý do]"*.

---

## 3. Trạng Thái Hiện Tại Của Hệ Thống (Live State)

### 3.1. Dịch Vụ Đang Chạy (Daemons & Endpoints)
- **FastAPI Backend:** Chạy tại port `8000` (`http://localhost:8000`), endpoints API `/api/v1/proposals`, `/api/v1/data-hub`, `/api/v1/agent/*`.
- **Next.js Web Portal:** Chạy tại port `3001` (`http://localhost:3001`), phục vụ chat, `/approvals`, `/data`, `/specs/[id]`.
- **Hạ Tầng Lưu Trữ & Vector:**
  - Qdrant Vector DB: Port `6333` (Collection `sdd_specs`).
  - PostgreSQL / pgvector: Port `5432` (Schema `sdd`).
  - Embedding Service: Ollama port `11434` (Model `bge-m3` 1024 dims).

### 3.2. Sức Khỏe Kho Tri Thức & Danh Mục Công Cụ MCP
- **Quy Mô:** Quản lý **23+ Tài liệu Specs** (`CYBEROS-01`, `CYBEROS-02`, `MYNOTCH-01`, `AGY-01`, `PKB-01..06`, `HR-M01..M05`, `HR-PROJECT`, `KB-01`), cùng hệ thống ADRs và Exemplars.
- **Danh Mục 8 Công Cụ MCP Active:**
  1. `search_knowledge(query, limit, project)`
  2. `get_spec_content(spec_id)`
  3. `list_specs(project)`
  4. `verify_citation(spec_id, quote)`
  5. `recall_guardrails(project, topic, limit)`
  6. `recall_exemplar(project, pattern)`
  7. `propose_knowledge_update(spec_id, title, section, proposed_content, rationale)`
  8. `query_cognitive_memory(query, project, intent_hint)`
- **Bộ Kiểm Thử:** 100% tests PASS (Pytest core, Vitest frontend).

---

## 4. Kế Hoạch Tiếp Theo (Future Roadmap)

1. **Tích hợp Tự Động Ingestion Trigger:** Hook tự động gọi `ingest_documents` khi phát hiện thay đổi trên branch git `main`.
2. **Dynamic Gotchas Extraction:** Khảo sát logs gỡ lỗi của các subagent để tự động dự thảo Gotchas mới chuyển về hàng đợi `/approvals`.
3. **Cross-Project Knowledge Graphs:** Mở rộng bảng liên kết thực thể (GraphStore) phục vụ phân tích tác động chéo khi thay đổi một module core.

---

## 5. Hướng Dẫn Tiếp Nhận Phiên Làm Việc Mới (Kickoff Reference)

```text
Hệ thống Personal-KB đã hoàn thành 100% Giai Đoạn 1, 2, 3 và Quản trị Tri thức (Active Cognitive Memory Fabric).
Toàn bộ thông số kiến trúc, ADRs, Exemplars, Guardrails và quy trình phê duyệt proposal đều đang hoạt động ổn định.
Tài liệu tham chiếu chi tiết:
- Spec bàn giao: knowledge/PKB-06.md
- Quy chuẩn ra lệnh duyệt: docs/KB_APPROVAL_COMMAND_SPEC.html
- Báo cáo Giai đoạn 3: docs/PHASE_3_COGNITIVE_MEMORY_FABRIC_REPORT.html
```
