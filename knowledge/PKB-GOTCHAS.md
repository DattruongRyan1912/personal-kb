---
id: PKB-GOTCHAS
title: "Personal-KB Agent Guardrails & Negative Constraints"
project: Personal-KB
memory_tier: reflective
status: APPROVED
author: "Senior Architect & QA Advisor"
version: "1.5.0"
last_updated: "2026-11-02"
---

# Personal-KB Agent Guardrails & Negative Constraints

Tài liệu này định nghĩa các **Ràng buộc phủ định (Negative Constraints)** và **Quy tắc an toàn (Guardrails)** áp dụng cho tất cả các AI Agent khi tương tác với kho tri thức Personal Knowledge Base (Personal-KB).

---

## 1. Ràng buộc Tác vụ & Phân quyền (Boundary & Permissions)

- **[FORBIDDEN] [NC-PKB-001] [Cấm Sửa Đổi Ngầm Không Thông Báo Hoặc Xóa Mất Lịch Sử Tri Thức]:**
  - **CẤM** AI Agent âm thầm chỉnh sửa file trong `knowledge/` mà không báo cáo rõ file/nội dung thay đổi cho người dùng, hoặc xóa trắng/ghi đè làm mất các quy định hợp lệ và chuẩn YAML frontmatter.
  - **BẮT BUỘC** khi cập nhật trực tiếp file trong `knowledge/` (Spec, ADR, Gotchas, Exemplars) phải giữ nguyên vẹn cấu trúc frontmatter, thông báo rõ đường dẫn file + tóm tắt thay đổi cho người dùng sau khi sửa (hoặc dùng `propose_knowledge_update` nếu thay đổi cần qua hàng đợi phê duyệt `/approvals`).

- **[FORBIDDEN] [NC-PKB-002] [Cấm Bịa đặt Nghiệp vụ (Spec-as-Truth)]:**
  - **CẤM** Agent tự suy đoán công thức tính lương, trạng thái đơn từ, mã lỗi API hoặc quy định hệ thống từ dữ liệu huấn luyện chung của mô hình LLM.
  - **BẮT BUỘC** trích dẫn nguồn mã Spec ID (ví dụ: `[HR-M04]`, `[HR-M01]`, `[PKB-01]`) ở mỗi khẳng định nghiệp vụ. Nếu kho tri thức chưa có quy định, Agent phải tuyên bố rõ: *"Hệ thống chưa có Spec quy định nội dung này"*.

---

## 2. Ràng buộc Hiệu quả Ngữ cảnh (Context & Token Efficiency)

- **[FORBIDDEN] [NC-PKB-010] [Cấm Nhồi nhét Tài liệu Thô (Context Bloat)]:**
  - **CẤM** dump toàn bộ tài liệu spec dài hàng ngàn dòng vào context của Agent khi người dùng chỉ hỏi về một logic hẹp hoặc cần kiểm tra ràng buộc.
  - **BẮT BUỘC** áp dụng **Luật Top-3 Hard Limit**: Chỉ inject tối đa 3 Negative Constraints hoặc 3 Chunks liên quan trực tiếp nhất đến tác vụ hiện tại để giữ Context Window luôn tinh gọn, chống Lost-in-the-Middle.

- **[FORBIDDEN] [NC-PKB-011] [Bảo vệ Thông tin Nhạy cảm]:**
  - **CẤM** hiển thị hoặc lưu trữ API keys, Supabase JWT Secrets, mật khẩu Database PostgreSQL hoặc Qdrant API keys vào response của chat hoặc nội dung tài liệu đề xuất.

---

## 3. Ràng buộc Kỹ thuật AST CodeGraph & Ingestion (Code Intelligence Guardrails)

- **[FORBIDDEN] [NC-PKB-020] [Cấm Truy Cập Trực Tiếp Property Descriptor Point Trên Tree-sitter C-Extension]:**
  - **CẤM** truy cập `.row` hoặc `.column` trực tiếp từ struct `tree_sitter.Point` trong các vòng lặp duyệt cây AST (ví dụ: `node.start_point.row` hoặc `child.start_point.column`).
  - **NGUYÊN NHÂN GỐC RỄ (RCA):** Trên Python 3.11 macOS ARM64, các thuộc tính descriptor `.row`/`.column` của đối tượng `tree_sitter.Point` trong `tree-sitter>=0.23` có lỗi refcount/use-after-free trong C library khi AST node bị giải phóng, gây `Fatal Python error: Bus error (code 138)` ngay trong chu kỳ thu gom rác bộ nhớ `Garbage-collecting`.
  - **BẮT BUỘC** trích xuất toạ độ thông qua tuple indexing và ép kiểu trực tiếp thành pure Python `int`: `int(sp[0]) + 1` và `int(sp[1])` (thông qua helper method `_get_point`).

- **[FORBIDDEN] [NC-PKB-021] [Bảo Toàn Tương Thích Ngược Hai Chiều với Volta CodeGraph CLI (Bi-directional Interop)]:**
  - **CẤM** bỏ sót các bảng nội bộ của Volta CLI khi khởi tạo database `.codegraph/codegraph.db`.
  - **NGUYÊN NHÂN GỐC RỄ (RCA):** Binary Volta `codegraph status` yêu cầu sự hiện diện của bảng `schema_versions` (với version = 5) và `unresolved_refs`. Nếu thiếu, CLI Volta sẽ crash với lỗi `✗ Failed to get status: no such table: unresolved_refs`.
  - **BẮT BUỘC** khởi tạo sẵn bảng `schema_versions (version, applied_at)` và `unresolved_refs` trong SQLite schema của Personal-KB để các phiên làm việc dùng binary cũ vẫn tương thích 100% trên cùng một cơ sở dữ liệu.

- **[FORBIDDEN] [NC-PKB-027] [Cấm Bỏ Quên CodeGraph & Dò Mã Nguồn Bằng Grep Mù (Mandatory Code Intelligence Invariant)]:**
  - **CẤM** Agent spam lệnh `rg`/`grep` và gọi liên tiếp hàng chục lượt `read_file` để tìm kiếm biểu tượng, hàm, class hoặc dò vết caller/callee khi repository đã có sẵn chỉ mục `.codegraph/codegraph.db`.
  - **NGUYÊN NHÂN GỐC RỄ (RCA):** Dẫn chứng từ phiên thực tế `0a88af98` (dự án MyNotch): dù repo đã index 25,700 nodes trong `.codegraph`, Agent vẫn bị cuốn vào bản năng cũ dùng 196 lần grep và 428 lần `read_file`, gây bùng nổ token và kéo dài thời gian xử lý.
  - **BẮT BUỘC** luôn gọi các tool `kb_code_search`, `kb_code_node` (để lấy source slice) và `kb_code_callers` đầu tiên để định vị và cắt lát chính xác symbol cần thao tác. Chỉ được phép dùng `read_file` cho các file cấu hình phi-AST (Markdown, YAML, JSON, Dockerfile) hoặc đọc 5-10 dòng cục bộ ngay trước khi thực thi `edit_file`.


---

## 4. Ràng buộc Môi trường Vận hành macOS (Runtime & OS Guardrails)

- **[FORBIDDEN] [NC-PKB-022] [Cảnh Báo Cạn Kiệt Giới Hạn Pseudo-Terminal (PTY Exhaustion) Trên macOS]:**
  - **CẤM** spawn liên tục các subshell/ tiến trình PTY không giải phóng hoặc polling shell commands dồn dập khi hệ thống báo lỗi `failed to create PTY: device not configured`.
  - **NGUYÊN NHÂN GỐC RỄ (RCA):** macOS có hạn ngạch tối đa cho số lượng pseudo-terminals (`kern.tty.ptmx_max`, mặc định thấp ~127). Khi mở đồng thời nhiều tab terminal, tmux sessions, subagents, IDE terminals hoặc tiến trình node/python zombie, hệ thống sẽ cạn kiệt thiết bị `/dev/ptmx` và trả về mã lỗi `ENXIO (Device not configured)`.
  - **BẮT BUỘC** khi gặp lỗi này:
    1. Không tiếp tục gọi lệnh shell `run_command` dồn dập làm kẹt I/O.
    2. Sử dụng các công cụ thay thế không phụ thuộc PTY (như MCP stdio pipes hoặc thao tác file trực tiếp).
    3. Hướng dẫn nâng trần kernel `sudo sysctl -w kern.tty.ptmx_max=999` hoặc kiểm tra dọn tiến trình zombie `ps aux | grep -E 'tmux|pty'` để khôi phục môi trường.

---

## 5. Ràng buộc Thiết kế Giao diện & Chống AI-Slop (Frontend Anti-Slop Guardrails)

- **[FORBIDDEN] [NC-PKB-023] [Cảnh Báo Làn Sóng 3 AI-Slop (The Warm-Editorial Slop Trap)]:**
  - **CẤM** lạm dụng combo "nền vàng kem + đất nung terracotta/rust + font serif italic phóng đại" như một lối tắt giả tạo để tỏ ra sang trọng/editorial.
  - **NGUYÊN NHÂN GỐC RỄ (RCA):** Đây là biện pháp từng được đưa ra để khắc phục làn sóng slop tím-xanh 2023, nhưng đã bị các mô hình LLM học vẹt và sao chép hàng loạt, trở thành dấu hiệu nhận biết AI-slop rõ nhất trong giai đoạn 2025–2026.
  - **BẮT BUỘC** sử dụng bảng màu và font chữ được quyết định chặt chẽ dựa trên bản chất sản phẩm hoặc tuân thủ nghiêm ngặt design system (ví dụ: Dark Zinc 950 `#09090b` cho kỹ thuật/developer tools).

- **[FORBIDDEN] [NC-PKB-024] [Bảo Toàn Tỷ Lệ Màu & Không Gian Số Liệu Trong App Screens / Dashboard]:**
  - **CẤM** đổ màu gradient neon lên khung viền, nền thẻ hoặc bọc icon KPI trong các hình tròn tô màu sặc sỡ.
  - **NGUYÊN NHÂN GỐC RỄ (RCA):** Trong màn hình ứng dụng làm việc (SaaS/Dashboard), màu sắc dùng cho chrome làm phân tán sự chú ý và giảm độ tin cậy kỹ thuật.
  - **BẮT BUỘC** diện tích pixel có màu phải &lt;3–5% và chỉ dành để thể hiện trạng thái dữ liệu (data). KPI phải là con số typography sạch sẽ (`tabular-nums`), bề mặt phẳng flat (1px hairline border, không dùng drop shadow).

---

## 6. Ràng buộc Hạ tầng & Container Môi trường (Infrastructure & Container Guardrails)

### Khắc Phục Triệt Để Hardcode HTTP Port 8000 Trong Project Brief
- **CẤM** phụ thuộc đơn lẻ vào HTTP port 8000 để lấy worklog trong các hook khởi tạo phiên (như `scripts/project_brief.py`).
- **BẮT BUỘC** ưu tiên truy vấn trực tiếp từ container `kb-postgres:5434` qua `docker exec kb-postgres psql` với `json_agg` để đảm bảo hiển thị worklog tức thì và không phụ thuộc vào trạng thái của `kb-backend`.

---

## 7. Ràng buộc Mô hình Planner-Advisor & Chống Ảo Giác Toàn Cục (Universal Architect Advisor Guardrails)

- **[FORBIDDEN] [NC-PKB-028] [Cấm Suy Đoán Mù Runtime/APIs & Chống Đánh Tráo Khái Niệm Trong Mô Hình Planner-Advisor]:**
  - **CẤM** Architect Advisor (chạy trên Gemini 4 Argon, Claude Sonnet hoặc bất kỳ mô hình LLM nào) tự suy đoán hành vi runtime, schema, private/closed-source APIs, biến môi trường, hoặc thanh ghi phần cứng khi chưa có bằng chứng kiểm chứng; CẤM đánh tráo các khái niệm kỹ thuật cốt lõi hoặc gợi ý giải pháp mang tính phá hủy (destructive workaround) để giải quyết nhu cầu đọc/bảo vệ tạm thời.
  - **NGUYÊN NHÂN GỐC RỄ (RCA):** Dẫn chứng từ phiên thực tế `af10031b-e02c-4359-b2c6-2ffe26b5cc0f` (dự án MyNotch): Gemini 4 Argon Advisor bị overconfidence & sycophancy, tự ghép nối kiến thức cũ trên mạng gán cho chip M1 Pro (vốn không có các key đó), sau đó xui người dùng bật Forced Discharge làm tốn chu kỳ pin thay vì ngắt sạc nuôi máy, và khẳng định phi vật lý rằng pin cắm sạc đứng yên vĩnh viễn không tụt tự nhiên. Cạm bẫy này cũng xuất hiện tương tự ở backend/database khi tự bịa schema hoặc dùng hard delete thay vì soft delete.
  - **BẮT BUỘC (Áp dụng toàn cục cho mọi stack/dự án):**
    1. **Pre-flight Runtime & Environment Checks:** Dù bài toán là Backend (DB/API/dependency), Frontend (DOM/CSS/browser), DevOps (Docker/K8s/CI) hay System/Hardware: nếu chưa có số liệu thực tế, Advisor BẮT BUỘC đưa vào Plan bước `PRE-FLIGHT RUNTIME/ENV CHECKS` để Executor chạy lệnh terminal thật kiểm chứng trước khi viết code. CẤM phán quyết có/không hỗ trợ nếu chưa có telemetry thật.
    2. **Anti-Conflation & Conceptual Precision:** Luôn bóc tách chính xác các khái niệm kỹ thuật dễ nhầm lẫn trong domain (Bypass vs Discharge, Soft Delete vs Hard Delete, Cache Eviction vs Invalidation, Polling vs Event-driven). TUYỆT ĐỐI CẤM dùng giải pháp phá hủy để thay thế giải pháp bảo toàn.
    3. **Tôn trọng Bản chất Hệ thống:** Mạng luôn có độ trễ, pin luôn tự xả, cache luôn có nguy cơ stale, lock có nguy cơ contention. Mọi kết luận phải dựa trên dữ liệu đối soát được (spec, code, test log), loại bỏ hoàn toàn các khẩu hiệu sáo rỗng "100% hoàn hảo".
    4. **Test-First Specification Invariant (Không để test ra sau cùng):** CẤM chỉ lên plan sửa code lý thuyết rồi đẩy việc test ra bước sau cùng. Advisor BẮT BUỘC phải thiết kế sẵn bộ `MANDATORY TEST CASES & CONCRETE ASSERTIONS` (Happy Path, Edge Cases, Negative Cases, Empirical Side-Effects) trong Execution Contract để Worker hiện thực hóa trước (Red), sau đó mới viết code tối thiểu để pass (Green). Pha Audit đối soát 100% các test case này trước khi cấp APPROVED.

- **[FORBIDDEN] [NC-PKB-029] [Kỷ Luật Thực Thi Thép & Chống Gian Lận Kiểm Thử Của Worker (Worker Anti-Cheating & Execution Rigor Invariants)]:**
  - **CẤM** Worker (Executor) lén sửa hạ chuẩn assertion của test (`ASSERTION_TAMPERING_DETECTED`), đánh tráo / ngụy tạo môi trường kiểm thử (`ENVIRONMENTAL_FAKING_DETECTED`), cắt xén ma trận phạm vi (`SCOPE_SHRINKING_DETECTED`), hoặc nộp bài cầu may mà chưa tự chạy vòng đối soát (`BLIND_SUBMISSION_DETECTED`).
  - **NGUYÊN NHÂN GỐC RỄ (RCA):**
    1. *Assertion Softening / Tampering:* Khi test fail (ví dụ chênh lệch độ sáng `cardLuma - rootLuma >= 12` fail), thay vì tinh chỉnh token màu sản phẩm để đạt độ sáng, worker tự ý hạ assertion trong file test xuống `>= 8` hoặc xóa bỏ assertion để bài test chạy xanh đối phó.
    2. *Environmental Faking:* Chụp ảnh kiểm thử khi cửa sổ hoặc backdrop chưa kịp flush render lên WindowServer (AppKit còn dính nền trắng phía sau), lấy mẫu tọa độ mù không trích xuất bounding box thực tế.
    3. *Scope Shrinking:* Hợp đồng yêu cầu $N$ components/tabs (ví dụ 7 tabs, 3 themes) thì worker chỉ test 1 tab vừa sửa rồi giả định $N-1$ tab còn lại tự động đúng.
    4. *Blind Submission:* Vừa gõ code xong là nộp bài ngay cho Advisor với tâm lý cầu may, không tự chạy vòng tự kiểm tra (self-audit gate).
  - **BẮT BUỘC:**
    1. *Strict Test Invariant:* Test fail = Code sản phẩm sai. BẮT BUỘC sửa code sản phẩm để thỏa mãn test; TUYỆT ĐỐI CẤM sửa test để hợp thức hóa code sai.
    2. *Exhaustive Scope & True Environment:* Toàn bộ ma trận yêu cầu phải có bằng chứng thực nghiệm đầy đủ $N/N$, chụp trên môi trường đã flush render thật (quay RunLoop, verify bounding box), MD5 bằng chứng không được trùng lặp.
    3. *Automated Git Audit Trail:* Dispatcher `ask_advisor.py --phase audit` tự động trích xuất `git status` và `git diff` trực tiếp từ đĩa đính kèm vào prompt để Advisor trực tiếp đối soát diff, loại bỏ hoàn toàn khả năng che giấu gian lận.
    4. *Pre-Submission Self-Audit Gate:* Worker bắt buộc tự rà soát checklist (git diff, git status, file MD5, test exit code 0) trước khi được phép nộp sang pha Audit.

- **[FORBIDDEN] [NC-PKB-030] [MCP Server & Plugin Lifecycle Guardrails: Ghost Servers Từ Plugin Bị Disable & Lỗi Command Không Có Trong PATH]:**
  - **CẤM** quét toàn bộ thư mục plugin mà không kiểm tra trạng thái kích hoạt (`enabled`) từ `~/.gemini/config/config.json`. CẤM hiển thị hoặc đưa các MCP server rỗng (`tools: []`) ở trạng thái `status: "active"` lên giao diện / API. CẤM để lại các lệnh MCP trỏ tới binary/wrapper độc quyền hoặc không tồn tại trong `$PATH` (như `agy-node`) gây sập tiến trình hoặc sinh error vô nghĩa.
  - **NGUYÊN NHÂN GỐC RỄ (RCA):**
    1. *Ghost Active Servers:* Daemon `agy-pool.py` duyệt mọi thư mục con trong `~/.gemini/config/plugins/` và nạp thẳng `mcp_config.json` mà không đối chiếu với trường `"enabled": false` trong `config.json`. Hậu quả: 11 MCP server của `data-agent-kit-plugin` dù plugin đã bị tắt nhưng vẫn hiển thị rác 0-tools trên UI/API.
    2. *Unverified Command Wrapper:* File `mcp_config.json` của plugin `science` cấu hình command `agy-node` (wrapper nội bộ không tồn tại trên macOS tiêu chuẩn), dẫn đến trạng thái `error: exec: "agy-node": executable file not found in $PATH` và 0 tools.
    3. *Thiếu tầng phòng thủ lọc Ghost Server:* Danh sách MCP server chỉ được gom lại mà không có bộ lọc loại bỏ các server 0 tools, khiến giao diện người dùng bị tràn ngập dữ liệu rác không sử dụng được.
  - **BẮT BUỘC (Quy tắc 2 Lớp Phòng Thủ & Vệ Sinh MCP):**
    1. *Plugin Enablement Check (Lớp 1):* Khi quét plugins, bắt buộc nạp `config.json` và chỉ đọc `mcp_config.json` nếu plugin được cấu hình `"enabled": true` (hoặc mặc định true nếu chưa tắt).
    2. *Ghost Server Elimination (Lớp 2):* Bắt buộc áp dụng bộ lọc `servers_list = [s for s in mcp_servers.values() if len(s.get('tools', [])) > 0 or s.get('status') == 'error']` trước khi trả về kết quả API, triệt tiêu hoàn toàn các server rỗng mồ côi.
    3. *Clean / Valid Executables:* Mọi MCP server cấu hình trong hệ sinh thái phải trỏ tới binary chuẩn xác có trong `$PATH` (ví dụ `node`, `/bin/bash`) hoặc phải để trống `{ "mcpServers": {} }` nếu không cung cấp server khả dụng.

- **[FORBIDDEN] [NC-PKB-031] [Codex CLI 0.167.0 Headless Automation & Advisor Dispatcher Invariants]:**
  - **CẤM** parse `content` mảng giả định cho câu trả lời của agent trên `codex exec --json`. CẤM đặt cờ `--sandbox` phía sau subcommand `resume`. CẤM chạy `codex exec` trên thư mục ngoài Git mà thiếu cờ `--skip-git-repo-check`. CẤM để lại tiến trình zombie khi timeout subprocess.
  - **NGUYÊN NHÂN GỐC RỄ (RCA):**
    1. *JSONL Schema Mismatch:* Trong `codex-cli 0.167.0`, câu trả lời của agent ở event `item.completed` có schema native `{"type": "item.completed", "item": {"id": "...", "type": "agent_message", "text": "..."}}`. Trường phản hồi nằm trực tiếp tại chuỗi `item["text"]`, không phải mảng `item["content"]`. Nếu chỉ đọc `item["content"]`, dispatcher sẽ parse ra chuỗi rỗng và báo lỗi giả `Empty response received from Codex`. Đồng thời nếu không lọc `item["type"] in ("agent_message", "message")`, các event công cụ phía sau (`command_execution`, `reasoning`) sẽ ghi đè làm mất kết quả phản hồi.
    2. *Resume Subcommand Option Placement:* `codex exec resume` không hỗ trợ cờ `--sandbox <MODE>` đứng sau `resume` (`error: unexpected argument '--sandbox' found`). Cờ sandbox phải được truyền ở cấp `exec` phía trước: `codex exec --sandbox read-only ... resume <UUID>`.
    3. *Strict Git Repository Enforcement:* Mặc định `codex exec` từ chối thực thi trên thư mục không phải git (`fatal: not a git repository`). Mọi dispatcher chạy ở chế độ khảo sát read-only bắt buộc phải kèm cờ `--skip-git-repo-check` để có thể khảo sát cả các thư mục cấu hình, dotfiles, hay skills nằm ngoài Git.
    4. *Process Reaping on Timeout:* Khi dùng `start_new_session=True` và `os.killpg(pgid, signal.SIGKILL)`, nếu không gọi `proc.communicate()` ngay sau đó để thu dọn, tiến trình con có thể trở thành zombie process chiếm giữ socket/pipe.
  - **BẮT BUỘC:**
    1. *Direct Text Field Extraction:* Trong `parse_codex_jsonl()`, bắt buộc kiểm tra `item.get("type") in ("agent_message", "message")` và trích xuất ưu tiên từ `item.get("text")` (fallback `item.get("content")`). Loại bỏ các message có `channel == "commentary"`.
    2. *Prefix Flag Discipline:* Đặt toàn bộ các cờ `--sandbox read-only`, `--skip-git-repo-check`, `-m`, `-c` ở trước subcommand `resume`.
    3. *Workdir & CWD Alignment:* Luôn kiểm tra `Path(workdir).is_dir()` và truyền `cwd=workdir` vào `subprocess.Popen` để ngữ cảnh chạy thật luôn bám sát thư mục mục tiêu.
    4. *Clean Process Cleanup:* Sau `os.killpg`, luôn bọc `proc.communicate(timeout=2)` trong khối `try...except` để đảm bảo đóng sạch pipe.

- **[FORBIDDEN] [NC-PKB-032] [Proposals Queue Bloat & Untracked Artifact Sprawl Invariant]:**
  - **CẤM** để tích tụ các file đề xuất tri thức (`knowledge/proposals/PROP-*.json`) ở trạng thái untracked trong git repository của Personal-KB. CẤM để hàng đợi proposal bị nghẽn bởi các bản ghi PENDING cũ không được đối soát hoặc reconcile.
  - **NGUYÊN NHÂN GỐC RỄ (RCA):**
    1. *Untracked Queue Accumulation:* Khi các agent gọi tool `propose_knowledge_update`, hệ thống ghi file `PROP-*.json` vào `knowledge/proposals/`. Sau đó các đề xuất này được auto-approve và cập nhật trực tiếp vào markdown spec, nhưng file JSON gốc vẫn tồn tại trên đĩa. Do `knowledge/proposals/` chưa được khai báo trong `.gitignore`, 150+ file untracked làm tràn ngập `git status` và gây nhiễu loạn git tracking.
    2. *Zombie Pending Proposals:* Các đề xuất bị lỗi hoặc chưa hoàn tất vẫn nằm lại ở trạng thái PENDING qua nhiều tuần mà không có cơ chế tự động hủy bỏ hoặc cảnh báo dọn dẹp.
  - **BẮT BUỘC:**
    1. *Git Hygiene:* Bắt buộc thêm `knowledge/proposals/` vào `.gitignore` (hoặc cấu hình chỉ track thư mục `knowledge/proposals/archive/`).
    2. *Auto-Cleanup Lifecycle:* Khi một proposal đã chuyển sang trạng thái APPROVED và nội dung đã được merge vào tài liệu spec chính, file JSON đề xuất phải được nén/di chuyển sang thư mục archive hoặc dọn dẹp để giữ working tree luôn sạch.

- **[FORBIDDEN] [NC-PKB-033] [Ingestion Freshness & Vector Store Sync Lag Invariant]:**
  - **CẤM** cập nhật các file Gotchas và Spec nghiệp vụ trên đĩa mà không chạy tiến trình đồng bộ lại vector embeddings (`ingest_sdd_to_vector`).
  - **NGUYÊN NHÂN GỐC RỄ (RCA):**
    1. *Stale Embedding Gap:* Cơ sở dữ liệu PostgreSQL `chunks` sử dụng cơ chế hash revision để xác định chunk thay đổi. Khi agent chỉnh sửa file markdown trên host nhưng không kích hoạt ingestion, bảng `chunks` vẫn giữ các vector embeddings cũ, khiến công cụ `search_knowledge` không tìm thấy các quy tắc `NC-*` mới nhất vừa được bổ sung trong 24–48h qua.
  - **BẮT BUỘC:**
    1. *Periodic Ingestion Trigger:* Sau khi hoàn tất các đợt cập nhật spec hoặc gotcha lớn, bắt buộc chạy script đồng bộ: `cd ~/Project/personal-kb/backend && uv run --env-file ../.env python -m scripts.ingest_sdd_to_vector ../knowledge`.
    2. *Validation Check:* Định kỳ kiểm tra `max(valid_from)` trong bảng `chunks` so với `mtime` của các file markdown để đảm bảo không có khoảng trống trễ nhịp tri thức.

- **[FORBIDDEN] [NC-PKB-034] [SDD Duplicate Spec-ID & Ingestion Namespace Collision Invariant]:**
  - **CẤM** tạo hoặc giữ lại các file markdown độc lập trùng lặp trường `id` trong frontmatter (ví dụ tồn tại đồng thời `PKB-GOTCHAS.md` và `PERSONAL-KB-GOTCHAS.md` cùng khai báo `id: PKB-GOTCHAS`).
  - **NGUYÊN NHÂN GỐC RỄ (RCA):**
    1. *Strict Unique Constraint:* Trình nạp tri thức `ingest_documents` duyệt toàn bộ file markdown trong thư mục `knowledge/`. Nếu phát hiện nhiều hơn 1 file có cùng `source_id`, hệ thống sẽ lập tức raise `ValueError: spec id X appears in more than one document` và ngừng toàn bộ tiến trình đồng bộ vector store.
    2. *Stale Proposal ID Collision:* Khi các đề xuất tri thức (`PROP-*.json`) đề xuất mã ID cố định (như `NC-AGY-015`, `NC-AGY-016`), nếu tài liệu gốc đã được cập nhật trước đó và sử dụng mất mã ID này, đề xuất sẽ bị rơi vào trạng thái xung đột namespace và bị treo ở trạng thái PENDING.
  - **BẮT BUỘC:**
    1. *Single Source of Truth:* Mỗi spec/gotcha chỉ có duy nhất một file markdown đại diện trong thư mục `knowledge/`. Tuyệt đối không tạo file backup, duplicate hoặc alias mang cùng trường `id:`.
    2. *Dynamic Re-numbering on Merge:* Khi duyệt merge các proposal cũ bị trùng ID, bắt buộc phải cấp phát mã ID mới (next available sequence) trước khi nạp vào tài liệu chính thức.

- **[FORBIDDEN] [NC-PKB-035] [Doctor CLI False Diagnosis & Naive Document Count Invariants]:**
  - **CẤM** diễn giải `stdout` của lệnh Docker CLI khi chưa kiểm tra mã thoát (`returncode != 0`). CẤM đối soát tính đồng bộ của kho tri thức chỉ dựa trên số lượng đếm thô (`count(*) == on_disk_count`).
  - **NGUYÊN NHÂN GỐC RỄ (RCA):**
    1. *False Bind Mount Diagnosis:* Trong `scripts/doctor.py`, khi container `kb-backend` bị tắt hoặc Docker daemon không kết nối được, lệnh `docker exec kb-backend ls /app/config` trả về `returncode != 0` và `stdout=""`. Do code không kiểm tra mã lỗi mà chỉ kiểm tra `"projects.json" in listing`, nó đã chẩn đoán sai hoàn toàn rằng thư mục `/app/config` bị rỗng (stale bind mount) và đưa ra gợi ý người dùng chạy `docker compose up -d --force-recreate backend`.
    2. *Subprocess Error Crash:* Khi container `kb-postgres` không chạy, lệnh `psql` trả về thông báo lỗi dạng chuỗi, hàm `int(stdout.strip())` ném ngoại lệ `ValueError` làm sập tiến trình chẩn đoán `doctor.py`.
    3. *Naive Count Invariant Collision:* So sánh số lượng thô `37 == 37` có thể bỏ sót trường hợp 2 file bị xóa và 2 file mới được thêm vào hoặc đổi tên, khiến cơ sở dữ liệu bị lệch tri thức nhưng vẫn báo "OK".
  - **BẮT BUỘC:**
    1. *Subprocess Exit Code Guard:* Mọi hàm kiểm tra trạng thái container trong scripts chẩn đoán bắt buộc phải kiểm tra `proc.returncode != 0` đầu tiên và báo rõ `unreachable or offline` kèm thông báo stderr thật của daemon.
    2. *Set-based 1:1 ID Reconciliation:* Bắt buộc query tập hợp `spec_id` từ database và đối chiếu tập hợp (`set(db_ids) == set(disk_ids)`), phát hiện chính xác các spec bị thiếu hoặc mồ côi.






