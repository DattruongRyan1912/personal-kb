---
id: PKB-02
title: Kiến trúc Memory Fabric, Vector Database & Hybrid Retrieval
project: Personal-KB
owner: Ryan Truong
status: active
tags: [retrieval, vector, memory-fabric, pgvector, qdrant, pkb]
---

# 1. Khái niệm Memory Fabric

**Memory Fabric** trong Personal-KB là tầng trừu tượng hoá việc lưu trữ và truy xuất tri thức dài hạn (Long-term Memory), cung cấp 3 cổng giao tiếp độc lập (Ports):
1. **DocumentStore:** Lưu trữ nguyên văn tài liệu Markdown đầy đủ frontmatter theo `spec_id`.
2. **VectorStore:** Lưu trữ các khối nội dung được chia nhỏ (Chunks), kèm vector nhúng và khoảng thời gian hiệu lực `[valid_from, valid_to)`.
3. **GraphStore:** Trích xuất và lưu trữ mạng lưới thực thể và quan hệ nghiệp vụ (Entity & Relationship Facts).

```
+-------------------------------------------------------------------------+
|                              MEMORY FABRIC                              |
+-------------------------------------------------------------------------+
|  +--------------------+  +--------------------+  +-------------------+  |
|  |   DocumentStore    |  |    VectorStore     |  |    GraphStore     |  |
|  | - Nguyên văn Spec  |  | - Chunks theo mục  |  | - Thực thể hệ thống|  |
|  | - Markdown + Header|  | - Vector Cosine    |  | - Quan hệ nghiệp vụ|  |
|  | - SHA-256 Hash     |  | - Bi-temporal UTC  |  | - Temporal edges  |  |
|  +--------------------+  +--------------------+  +-------------------+  |
+-------------------------------------------------------------------------+
```

---

# 2. Quy Trình Ingestion & Bi-temporal Versioning

Khi tài liệu Markdown được đưa vào kho tri thức thông qua lệnh `ingest_documents`:

1. **Frontmatter Parsing:** Trích xuất các trường `id`, `title`, `owner`, `status`, `tags`.
2. **Structural Chunking:** Tách văn bản theo các tiêu đề `#`, `##`, `###`. Mỗi chunk đại diện cho một điều khoản hoặc quy định logic độc lập.
3. **Chunk Keying:** Tạo định danh duy nhất cho từng chunk: `{spec_id}#{section_slug}`.
4. **Bi-temporal Timestamping:**
   - Khi một chunk mới xuất hiện: gán `valid_from = now()`, `valid_to = null` (đang có hiệu lực).
   - Khi một chunk bị xóa hoặc sửa đổi nội dung: cập nhật chunk cũ với `valid_to = now()`, đồng thời tạo chunk mới với `valid_from = now()`.
   - Cơ chế này cho phép hệ thống trả lời các câu hỏi về quá khứ mà không bao giờ làm mất lịch sử tiến hóa của tài liệu đặc tả.

---

# 3. Cơ Chế Truy Xuất Lai (Hybrid Retrieval) & Reranking

Personal-KB áp dụng chiến lược truy xuất 2 giai đoạn (Two-Stage Retrieval) để đạt độ chính xác tối đa:

## 3.1 Giai Đoạn 1: Tìm Kiếm Song Song (Hybrid Search)
- **Vector Cosine Search:** Sử dụng mô hình nhúng (Embedding) để tìm các chunk có khoảng cách ngữ nghĩa gần nhất (Cosine Similarity >= 0.65).
- **BM25 / Lexical Search:** Tìm kiếm chính xác theo từ khóa kỹ thuật (mã lỗi HTTP, tên bảng cơ sở dữ liệu, mã định danh `SPC-1`, `PKB-01`).

## 3.2 Giai Đoạn 2: Tái Sắp Xếp (Cross-Encoder Reranking)
- Các kết quả từ giai đoạn 1 được đưa qua mô hình Reranker (BGE-Reranker-Large hoặc TEI server).
- Mô hình đánh giá cặp câu hỏi - đoạn trích với độ sâu cao, lọc bỏ hoàn toàn các đoạn trích nhiễu và gán điểm tương quan cuối cùng (`score`).
- Chỉ các kết quả vượt ngưỡng tin cậy mới được cấp cho LLM Agent làm ngữ cảnh tạo câu trả lời (Grounding).
