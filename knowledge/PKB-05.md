---
id: PKB-05
title: Hướng dẫn Cài đặt, Vận hành & Triển khai Personal Knowledge Base
project: Personal-KB
owner: Ryan Truong
status: active
tags: [devops, setup, runbook, deployment, docker, pkb]
---

# 1. Yêu Cầu Môi Trường (Prerequisites)

Để chạy trọn vẹn hệ thống Personal-KB, môi trường máy phát triển cần:
- **Python:** 3.11.x (quản lý qua `uv`).
- **Node.js:** v20.x hoặc v22.x LTS (quản lý qua `pnpm` hoặc `npm`).
- **Docker & Docker Compose:** phiên bản 24.x trở lên.

---

# 2. Cấu Hình Biến Môi Trường (.env)

Tạo file `.env` tại thư mục gốc dự án:
```bash
# Copy .env.example thành .env rồi điền giá trị (không commit .env)
# PostgreSQL 17 + pgvector (docker compose dựng POSTGRES_URL từ các biến này)
PG_USER=kb_user
PG_PASSWORD=...
PG_DATABASE=knowledge_db

# Model trả lời (API tương thích OpenAI: DeepSeek, OpenAI hoặc Ollama)
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# Embedding chạy local qua Ollama (bge-m3, 1024 chiều)
EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1
EMBEDDING_API_KEY=ollama
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIMENSIONS=1024

# Dev Login (local, không cần Supabase cloud)
SUPABASE_JWT_SECRET=...
```

---

# 3. Khởi Động Dịch Vụ Hệ Thống

### 3.1 Khởi động Hạ tầng Docker (Databases & Services)
```bash
docker compose up -d
```
Lệnh trên khởi chạy 4 container, mọi cổng chỉ mở cho `127.0.0.1`:
- `kb-postgres`: PostgreSQL 17 + pgvector (`pgvector/pgvector:pg17`) trên cổng `5434`.
- `kb-redis`: Redis 7 (`redis:7-alpine`) trên cổng `6380`.
- `kb-backend`: FastAPI trên cổng `8000`.
- `kb-frontend`: Next.js trên cổng `3000`.

Reranker `bge-reranker-v2-m3` chạy ngoài Docker qua launchd trên cổng `8081` (xem `integrations/launchd/`).

### 3.2 Chạy Backend Core API (FastAPI)
```bash
cd backend
uv run --env-file ../.env uvicorn personal_kb.main:create_app --factory --port 8000 --reload
```
Kiểm tra sức khỏe dịch vụ:
```bash
curl http://localhost:8000/health
# Trả về: {"status": "ok"}
```

### 3.3 Chạy Frontend Web Chat & Governance UI (Next.js)
```bash
cd frontend
npm install
npm run dev
```
Truy cập giao diện:
- Giao diện trò chuyện: `http://localhost:3001/`
- Giao diện phê duyệt tri thức: `http://localhost:3001/approvals`

---

# 4. Hướng Dẫn Nạp Tri Thức Mới (Ingestion)

Bất kỳ khi nào bạn thêm hoặc sửa đổi file Markdown trong thư mục `knowledge/`:

Chạy script tự động:
```bash
./scripts/ingest.sh
```
Hoặc chạy trực tiếp bằng `uv`:
```bash
cd backend
uv run --env-file ../.env python -m scripts.ingest_sdd_to_vector ../knowledge
```

Nếu muốn xóa hoàn toàn một spec khỏi kho tri thức:
```bash
uv run --env-file ../.env python -m scripts.ingest_sdd_to_vector --delete PKB-01
```

---

# 5. Kiểm Thử Chất Lượng Hệ Thống (Quality Gates)

### 5.1 Backend Pytest Suite
```bash
cd backend
uv run pytest tests/
```

### 5.2 Frontend Vitest & TypeScript Typecheck
```bash
cd frontend
npm run typecheck
npm test -- --run
```
