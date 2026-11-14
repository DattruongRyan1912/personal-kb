---
id: PKB-01
title: Tổng quan & Kiến trúc Hệ thống Personal Knowledge Base (Personal-KB)
project: Personal-KB
owner: Ryan Truong
status: active
tags: [architecture, overview, pkb, personal-kb]
---

# 1. Giới thiệu dự án Personal Knowledge Base (Personal-KB)

**Personal Knowledge Base (Personal-KB)** là một hệ sinh thái lưu trữ, tra cứu và quản trị tri thức đặc tả nghiệp vụ (Software Design Document - SDD) thông minh, được fork và phát triển độc lập từ kiến trúc CyberOS AI.

Dự án ra đời nhằm giải quyết bài toán:
- Cung cấp một kho tri thức cá nhân riêng biệt, bảo mật và hoàn toàn tự chủ.
- Xóa bỏ sự phụ thuộc vào các nền tảng SaaS đóng gói, cho phép tích hợp trực tiếp vào quy trình làm việc của Developer và AI Agent.
- Triệt tiêu hiện tượng ảo giác (hallucination) của mô hình ngôn ngữ lớn (LLM) bằng cơ chế **Spec-as-Truth** và kiểm chứng trích dẫn nguồn gốc (Citation Verification).

---

# 2. Kiến trúc Tổng thể (Dual Protocol Architecture)

Personal-KB áp dụng kiến trúc **Giao thức Kép (Dual Protocol)**, tách biệt rõ ràng giữa trải nghiệm người dùng cuối (Human Protocol) và kênh tương tác máy-với-máy (Agent Protocol):

```
+-----------------------------------------------------------------------------------+
|                           PERSONAL KNOWLEDGE BASE (PKB)                           |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  [ HUMAN PROTOCOL - Giao diện Web ]             [ AGENT PROTOCOL - M2M & MCP ]    |
|  - Next.js 16 (App Router, Tailwind, Lucide)     - Model Context Protocol (MCP 2.x)|
|  - Chat UI với SSE Streaming & Citations         - Stdio & Streamable SSE Transports|
|  - Trang Quản trị Phê duyệt (/approvals)         - REST M2M API (/api/v1/agent/*)  |
|                                                                                   |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                             FASTAPI CORE BACKEND                                  |
|  - ToolRegistry & Agent Orchestration (LangChain / LangGraph)                     |
|  - Human Gate & Proposal Store (Optimistic Concurrency Control - OCC)             |
|  - DocumentStore & Ingestion Engine (Bi-temporal chunking & Embedding)             |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                           MEMORY FABRIC & DATA LAYER                              |
|  - PostgreSQL 17 + pgvector (Port 5434): Vector Embeddings (BGE-M3, 1024 dims)    |
|  - Reranker bge-reranker-v2-m3 (Port 8081, launchd): xếp hạng lại kết quả search |
|  - Redis 8 (Port 6379): Session Memory & Sliding Conversation History             |
|  - File-based Staging Store (knowledge/proposals/*.json): Git-trackable proposals |
+-----------------------------------------------------------------------------------+
```

## 2.1 Các Cổng Dịch Vụ và Cấu Trúc Runtime
1. **Frontend Web UI:** Port `3000` (Next.js 16 Standalone, React 19).
2. **Backend API Core (Local):** Port `8000` (FastAPI, Uvicorn).
3. **Reranker (launchd, ngoài Docker):** Port `8081` (bge-reranker-v2-m3 trên GPU của Mac).
4. **PostgreSQL 17 (pgvector):** Port `5434` (Lưu trữ vector chunks, toàn văn tài liệu, đồ thị và worklog).
5. **Redis Cache:** Port `6380` (Lưu phiên trò chuyện và bộ nhớ ngắn hạn).

---

# 3. Các Phân Hệ Cốt Lõi

## 3.1 Kênh Hỏi Đáp Tri Thức (Smart Chat Interface)
- Giao tiếp trực tiếp với AI thông qua Server-Sent Events (SSE) mượt mà.
- Mọi câu trả lời bắt buộc phải trích dẫn mã tài liệu Spec ID (ví dụ: `[Tên tài liệu](PKB-01)`).
- Click vào Badge trích dẫn mở ngăn kéo Slide-over Drawer để đọc trực tiếp tài liệu gốc mà không làm gián đoạn cuộc trò chuyện.

## 3.2 Cổng Quản Trị & Phê Duyệt Tri Thức (Knowledge Governance)
- Nằm tại đường dẫn `/approvals`.
- Đóng vai trò là **Human Gate**: AI Agent chỉ có quyền đề xuất cập nhật khi phát hiện dữ liệu cũ hoặc mâu thuẫn (`PENDING`).
- Con người (Reviewer/Admin) có toàn quyền xem trước nội dung Markdown, đối soát lý do cập nhật và bấm **Phê duyệt (Approve)** hoặc **Từ chối (Reject)**.
- Khi phê duyệt, hệ thống tự động ghi đè file Markdown spec, cập nhật DocumentStore và sinh lại vector nhúng vào database theo thời gian thực.
