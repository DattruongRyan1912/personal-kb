# 🧠 Personal Knowledge Base (Personal-KB)

Hệ thống Kho Tri Thức và Trợ lý AI Hỏi Đáp Nghiệp vụ Thông minh, tối ưu hóa chi phí cho cá nhân và doanh nghiệp.

- **Backend:** FastAPI + LangChain (Agentic RAG, Tool Calling, Vector & Relational Memory).
- **Database:** PostgreSQL 17 + `pgvector` (Lưu trữ văn bản và vector 1024-dim).
- **Caching & Session Memory:** Redis 7.
- **Frontend UI:** Next.js 16 (React 19, Tailwind CSS, SSE Streaming, Thẻ dẫn chứng / Citation Badges, Dev Login).
- **Mô hình AI:** Tối ưu hóa lai giữa **DeepSeek API (`deepseek-chat`)** cho suy luận và **Local Ollama (`bge-m3`)** cho embeddings (0đ chi phí nhúng).

---

## 🚀 Khởi chạy nhanh (Quick Start)

### 1. Yêu cầu hệ thống
- Đã cài đặt [Docker](https://www.docker.com/) & Docker Compose.
- Đã cài đặt [Ollama](https://ollama.ai/) và đã pull model embedding:
  ```bash
  ollama pull bge-m3
  ```

### 2. Cấu hình môi trường
Tạo file `.env` từ file mẫu:
```bash
cp .env.example .env
```
Mở `.env` và điền API key DeepSeek của bạn:
```env
OPENAI_API_KEY=sk-your_deepseek_api_key_here
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
AGENT_READ_SPECS=false
```

### 3. Khởi động hệ thống
Chạy toàn bộ dịch vụ (Postgres, Redis, Backend, Frontend):
```bash
docker compose up -d --build
```
Kiểm tra trạng thái:
- **Web UI Chat:** `http://localhost:3000`
- **Backend API Health:** `http://localhost:8000/health` (trả về `{"status":"ok"}`)

### 4. Nạp tri thức vào kho (Ingestion)
Đặt các file tài liệu Markdown nghiệp vụ của bạn vào thư mục `./knowledge/` (đã có sẵn 6 file URD nghiệp vụ mẫu). Sau đó chạy:
```bash
./scripts/ingest.sh
```
Hệ thống sẽ tự động phân mảnh (chunking) và nhúng vector vào PostgreSQL.

---

## 💬 Trải nghiệm Hỏi đáp

### Cách 1: Qua Web Chat UI
1. Mở trình duyệt tại **`http://localhost:3000`**.
2. Nhấn nút **"Đăng nhập dev"** (chế độ local dev đã bật sẵn).
3. Bắt đầu hỏi đáp với tốc độ streaming cực nhanh và click vào các thẻ Citation màu xanh để xem nguồn dẫn chứng.

### Cách 2: Qua Terminal CLI
```bash
./scripts/chat.sh "Theo tài liệu Module 04, quy định về làm thêm giờ OT và bảng hệ số tính như thế nào?"
```

---

## ⚡ Cơ chế Tối ưu Chi phí (Cost Optimization)

Dự án này tích hợp sẵn cơ chế **Chunk-based RAG (`AGENT_READ_SPECS=false`)**:
- **Không nhồi cả file lớn vào prompt:** Chỉ lọc ra Top 5 đoạn trích ngữ nghĩa liên quan nhất (~1.500 tokens).
- **Chi phí cực thấp:** Mỗi câu hỏi chỉ tiêu tốn khoảng **5 đến 25 VNĐ** (rẻ hơn 95% so với phương pháp RAG truyền thống nhồi nguyên văn cả tài liệu).
- **Hỗ trợ DeepSeek Context Caching:** Các câu hỏi liên tiếp trong cùng một phiên chat được hưởng đơn giá Cache Hit rẻ hơn 10 lần.

---

## 🔌 Giao thức Mở rộng (MCP Server & Multi-Agent)

- **Model Context Protocol (MCP):** Chạy MCP Server qua Streamable HTTP SSE tại endpoint `/mcp` hoặc chạy STDIO mode qua script `./scripts/mcp_server.sh` (chạy trên máy từ `backend/.venv`, cần `cd backend && uv sync` một lần; không rớt khi `kb-backend` khởi động lại) để tích hợp trực tiếp vào Claude Desktop, Kiro, Cursor hoặc IDE.
- **Agent Protocol (`/api/v1/agent/*`):** Giao diện chuẩn M2M (Machine-to-Machine) cho phép các AI Agent khác truy vấn tri thức, bảo vệ bởi header `X-Agent-Key`.
- **Human Protocol (`/api/v1/human/*`):** Giao diện REST/SSE tối ưu cho người dùng cuối trên Web UI.

---

## 🧪 Báo cáo Kiểm thử & Đo đạc Thực tế (Test Evidence)

Dự án có đầy đủ dữ liệu kiểm nghiệm thực tế từng bước trong quá trình phát triển:
- **Báo cáo HTML Trực quan:** Xem file [`test_evidence/TEST_EVIDENCE_REPORT.html`](./test_evidence/TEST_EVIDENCE_REPORT.html) (giao diện dark mode, biểu đồ số liệu, đối soát từng câu hỏi kiểm thử).
- **Chi tiết Test Cases:** Xem file [`test_evidence/test_cases.json`](./test_evidence/test_cases.json) (bao gồm kịch bản độ khó cực cao cross-module tính toán lương, OT, BHXH, Thuế TNCN và phát hiện vi phạm pháp luật).
- **Benchmark Chi phí Token:** Xem file [`test_evidence/cost_benchmark.json`](./test_evidence/cost_benchmark.json) (đo lường tiết kiệm ~95% chi phí token).
- **Tài liệu Bàn giao:** Xem file [`HANDOVER.html`](./HANDOVER.html).

---

## 📚 Tài liệu kỹ thuật

- [`docs/architecture.md`](./docs/architecture.md): kiến trúc stack, luồng MCP, ingest và phê duyệt, worklog và project brief cho agent.
- [`docs/prompts.md`](./docs/prompts.md): từ điển các prompt trong `backend/prompts/`.
- [`docs/add-a-tool.md`](./docs/add-a-tool.md): hướng dẫn thêm một tool cho agent.
- Chạy toàn bộ test với Postgres thật của stack: `./scripts/test.sh` (cần `kb-backend` đang chạy; tham số thêm được chuyển cho pytest).
- Sao lưu worklog (dữ liệu duy nhất không dựng lại được từ `knowledge/`): `./scripts/backup_worklog.sh` rồi commit `docs/worklog/worklog.jsonl`. Khôi phục: `docker exec -i kb-backend python -m scripts.worklog_backup restore < docs/worklog/worklog.jsonl`.
- Ép ghi worklog (Claude Code và AGY): hook `Stop` chạy `scripts/worklog_guard.py` (Claude: `~/.claude/settings.json`; AGY: `Stop` trong `integrations/agy-brief-plugin/hooks.json`, chép sang `~/.gemini/config/plugins/kb-brief-injector/`). Lượt nào sửa code trong repo có trong `config/projects.json` mà chưa gọi `log_progress` sẽ bị giữ lại một lần để agent ghi (và đề xuất sửa spec nếu cần); nếu vẫn không ghi, hook tự ghi một mục `[tự động]`.
- Kiểm tra stack và cấu hình MCP của agent khi có gì đó "âm thầm" sai (mount `config/` cũ, config desktop bị app ghi đè, thiếu tài liệu, reranker tắt): `/usr/bin/python3 scripts/doctor.py`.

---

## 📁 Cấu trúc thư mục

```
personal-kb/
├── backend/            # Mã nguồn FastAPI, Services, Tools, Prompts, MCP Server
├── frontend/           # Giao diện Next.js 16 Chat UI (React 19, Tailwind)
├── knowledge/          # 7 tài liệu Markdown đặc tả nghiệp vụ (5.342 dòng)
├── test_evidence/      # Dữ liệu kiểm nghiệm thực tế, benchmark & báo cáo HTML
├── scripts/            # Script tiện ích (ingest.sh, chat.sh, mcp_server.sh)
├── docker-compose.yml  # File orchestration Docker (Postgres, Redis, Backend, Frontend)
├── .env.example        # Mẫu biến môi trường an toàn
├── HANDOVER.html       # Báo cáo bàn giao nhanh định dạng HTML
└── README.md           # Hướng dẫn dự án
```
