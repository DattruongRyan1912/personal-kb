# Agent Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude and AGY opening a session in a mapped repo get a short "project brief" (recent worklog, git state, the other runtime's last session), and can write progress with one MCP call that needs no human approval.

**Architecture:** An append-only `worklog_entries` table in kb-postgres, written and read through two MCP tools and a REST route in kb-backend. A stdlib-only host script `scripts/project_brief.py` builds the brief from that REST route, live `git`, and local Claude/AGY transcripts. Claude loads it through a SessionStart hook; AGY through a rule in `~/.agents/GLOBAL.md` (hook injection was tested and did not work).

**Tech Stack:** Python 3.11, FastAPI, asyncpg/pgvector Postgres, `mcp` MCPServer, pytest + pytest-asyncio (backend venv); Python 3 stdlib for the host script; docker compose.

**Spec:** `docs/superpowers/specs/2026-10-24-agent-continuity-design.html` (approved 2026-10-24). Read it first; section numbers below refer to it.

## Global Constraints

- Work on branch `feat/agent-continuity`. Commit steps run only after Ryan says to commit; no `Co-Authored-By` or "Generated with" lines.
- Never write anything under `knowledge/`; never change existing API routes or MCP tools' behavior.
- Brief: ≤ 2500 characters; script always exits 0; p95 < 3 s; REST timeout 2 s.
- Brief sections and limits: worklog 5 newest entries; git ≤ 10 uncommitted file names, ≤ 8 commits by `git_author` in the last 7 days; "Phiên trước" = newest main session of the *other* runtime.
- Worklog `kind` ∈ {`progress`, `decision`, `gotcha`, `handoff`}; `summary` required, ≤ 2000 chars; `next_steps` ≤ 2000 chars; `project` must be a key of `config/projects.json`.
- Host script: stdlib only, must run on **`/usr/bin/python3` (3.9.6)** — the hook and the AGY rule both call that exact path. So: `from __future__ import annotations`, no `match`, no `dataclass(kw_only=…)`, no `datetime.UTC` (use `timezone.utc`), no 3.10+ stdlib APIs. Never prints model thinking; redacts secrets.
- CLI scenarios (`claude -p`, `agy -p`, benchmark) run in a throwaway repo `~/Project/_continuity-bench` mapped as project `Continuity-Bench` only while testing, so they never become a real repo's "Phiên trước"; remove the mapping (and log it) when Task 11 ends.
- Every edit to a file outside the repo: backup `<file>.bak-YYYYMMDD-HHMMSS` first, then append one line to `docs/agent-continuity/config-changes.log` (`time | file | backup | change | undo`), no secret values.
- Run backend tests from `backend/`: `uv run pytest <path> -q`. Postgres tests need `POSTGRES_URL=postgresql://kb_user:kb_secret_password_2026@localhost:5434/knowledge_db` (stack is up on :5434).
- Rebuild/restart only `kb-backend` (`docker compose up -d --build backend` from repo root); never touch the CyberOS stack.

## Review Focus

1. A cwd given through a symlink (`/tmp` → `/private/tmp`), with a trailing slash, or as a subdirectory/worktree of a mapped repo → resolves to that project; a sibling with a shared prefix (`~/Project/HRM2`) does not.
2. A transcript line that is malformed, half-written (file being appended), or huge → skipped or truncated, never a crash or a 2 MB brief.
3. kb-backend down, refusing, or slower than 2 s → one line `worklog: không truy cập được`, rest of the brief printed, exit 0 under 3 s.
4. Secret-looking strings (`sk-…`, `Bearer …`, `ghp_…`, `AQ.…`, `password=…`) in a transcript **or in a worklog entry** → redacted in the brief.
5. A mapped repo path that does not exist or is not a git repo, or `git` missing from PATH → git section omitted, no traceback.

Each line has a test in Task 6 or Task 7.

---

### Task 1: Project map and worklog domain

**Files:**
- Create: `config/projects.json`
- Create: `backend/personal_kb/services/worklog.py`
- Modify: `backend/personal_kb/core/config.py` (add one Settings field)
- Test: `backend/tests/test_worklog.py`

**Interfaces:**
- Produces:
  - `config/projects.json`: `{"<project>": {"repo": "~/Project/…", "git_author": "dattruong19122003@gmail.com"}}` with exactly Demo-Core → `~/Project/HRM`, CyberOS → `~/Project/CyberOS`, MyNotch → `~/Project/MyNotch`, AGY-Remote-Hub → `~/Project/agy-remote-hub`, Personal-KB → `~/Project/personal-kb`.
  - `Settings.projects_config: Path = Path("../config/projects.json")` (env `PROJECTS_CONFIG`).
  - `WORKLOG_KINDS: tuple[str, ...] = ("progress", "decision", "gotcha", "handoff")`, `MAX_TEXT = 2000`.
  - `load_project_names(path: Path) -> frozenset[str]` (missing/invalid file → `frozenset()`).
  - `@dataclass(frozen=True) class NewWorklogEntry: project, kind, summary, next_steps="", agent="", session_id="", branch=""` (all `str`).
  - `@dataclass(frozen=True) class WorklogEntry(NewWorklogEntry): id: int; created_at: datetime` — order fields so the subclass is valid (put defaults last or use `kw_only=True`).
  - `validate_entry(entry: NewWorklogEntry, projects: frozenset[str]) -> NewWorklogEntry` — strips text, raises `WorklogValidationError(ValueError)` with a Vietnamese message naming the bad field.
  - `class WorklogStore(Protocol)`: `async ensure() -> None`, `async add(entry: NewWorklogEntry) -> WorklogEntry`, `async recent(project: str, *, limit: int = 10, kind: str = "") -> list[WorklogEntry]`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_worklog.py`:
  - `test_load_project_names_reads_keys` (tmp file with two projects → both names).
  - `test_load_project_names_missing_file_is_empty`.
  - `test_the_repo_map_lists_the_five_projects` — loads the real `../config/projects.json`, asserts the five names and that every `git_author` is `dattruong19122003@gmail.com`.
  - `test_validate_rejects_unknown_project`, `test_validate_rejects_unknown_kind`, `test_validate_rejects_empty_summary`, `test_validate_rejects_summary_over_2000` (2001 chars), `test_validate_strips_whitespace` (`"  x  "` → `"x"`).
- [ ] **Step 2:** `cd backend && uv run pytest tests/test_worklog.py -q` → FAIL (module missing).
- [ ] **Step 3:** Create `config/projects.json`, the Settings field, and `services/worklog.py` with the interfaces above.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat(worklog): add project map and worklog domain`.

### Task 2: Postgres worklog store and wiring

**Files:**
- Create: `backend/personal_kb/infrastructure/postgres/pg_worklog_store.py`
- Modify: `backend/personal_kb/infrastructure/postgres/schema.sql` (new table + index)
- Modify: `backend/personal_kb/infrastructure/memory_backend.py` (`MemoryStores.worklog`)
- Modify: `backend/personal_kb/tools/base.py` (`ToolContext.worklog`)
- Modify: `backend/personal_kb/bootstrap.py` (pass `worklog=stores.worklog`)
- Test: `backend/tests/test_pg_worklog_store.py`

**Interfaces:**
- Consumes: Task 1 `NewWorklogEntry`, `WorklogEntry`, `WorklogStore`.
- Produces:
  - Table `worklog_entries(id bigserial PK, project text NOT NULL, kind text NOT NULL, summary text NOT NULL, next_steps text NOT NULL DEFAULT '', agent text NOT NULL DEFAULT '', session_id text NOT NULL DEFAULT '', branch text NOT NULL DEFAULT '', created_at timestamptz NOT NULL DEFAULT now())`, index `(project, created_at DESC)`. `IF NOT EXISTS` like the rest of `schema.sql`.
  - `class PgWorklogStore(pool: PoolLike, *, schema: str, dimensions: int)` implementing `WorklogStore`; `ensure()` calls `ensure_schema`; every query inside `postgres_unavailable()`; `recent` orders newest first.
  - `MemoryStores.worklog: WorklogStore | None = None` (last field); postgres backend sets a `PgWorklogStore`, qdrant-neo4j leaves `None`.
  - `ToolContext.worklog: Any = None` and `ToolContext.projects: frozenset[str] = frozenset()` (last fields, so existing `ToolContext(retriever=…, documents=…)` calls keep working). `bootstrap.services` fills `projects` from `load_project_names(settings.projects_config)`; MCP tools and the REST route read the project list from here, never from `get_settings()`.
  - `PgWorklogStore` ensures its table lazily: the first `add`/`recent` in a process calls `ensure()` once (guarded by an `asyncio.Lock` + flag), because nothing calls `ensure()` at app or MCP startup today (`api/system.py` is the only caller).
  - No delete/update methods (append-only).

- [ ] **Step 1: Write the failing tests** using the `pg_pool`/`pg_schema` fixtures from `conftest.py`:
  - `test_add_then_recent_returns_newest_first` (add 3, `recent(limit=2)` → the last two, newest first, ids and `created_at` set).
  - `test_recent_filters_by_project_and_kind`.
  - `test_ensure_is_idempotent` (call twice).
  - `test_first_add_creates_table_without_explicit_ensure` (fresh schema, `add` without `ensure()` → succeeds).
- [ ] **Step 2:** `cd backend && POSTGRES_URL=… POSTGRES_REQUIRED=1 uv run pytest tests/test_pg_worklog_store.py -q` → FAIL.
- [ ] **Step 3:** Implement store, schema, and the three wiring edits.
- [ ] **Step 4:** Same command → PASS; then `uv run pytest -q -x --ignore=tests/test_compose.py` → no new failures versus `main` (record the baseline first; `test_compose.py` targets a CyberOS-era compose layout and is out of scope).
- [ ] **Step 5: Commit** `feat(worklog): add Postgres worklog store`.

### Task 3: MCP tools `log_progress` and `get_worklog`

**Files:**
- Modify: `backend/personal_kb/mcp/server.py` (two tools before the resource)
- Modify: `backend/personal_kb/mcp/cli.py` (startup log line lists the new tools)
- Test: `backend/tests/test_mcp_server.py` (append)

**Interfaces:**
- Consumes: `ToolContext.worklog`, `ToolContext.projects`, `validate_entry`.
- Produces (tool names and parameters are the contract agents and GLOBAL.md use):
  - `log_progress(project: str, summary: str, kind: str = "progress", next_steps: str = "", agent: str = "", session_id: str = "", branch: str = "") -> str` → `"✅ Đã ghi worklog #<id> cho <project>"`; validation error → text starting `"Lỗi:"`; `ctx.worklog is None` → `"Lỗi: worklog cần MEMORY_BACKEND=postgres"`; store unavailable → `"Lỗi: …"`. Never raises.
  - `get_worklog(project: str, limit: int = 10, kind: str = "") -> str` → one line per entry `"#<id> <YYYY-MM-DD HH:MM> [<agent>/<kind>] <summary>"` plus `"  → tiếp: <next_steps>"` when set; none → `"Chưa có worklog cho <project>."`; `limit` clamped to 1..50.
  - Description of `log_progress` (Vietnamese, ≥ 2 sentences) must say: ghi thẳng, không cần duyệt, không phải requirement; gọi khi xong một bước đáng kể, khi ra quyết định, khi gặp cạm bẫy, và trước khi kết thúc/bàn giao; khi người dùng nói "cập nhật tiến độ" thì dùng tool này thay vì `propose_knowledge_update`.

- [ ] **Step 1: Write the failing tests** with a `FakeWorklogStore` (in-memory list) set on `ToolContext(..., worklog=FakeWorklogStore(), projects=frozenset({"Demo-Core"}))`:
  - `test_log_progress_writes_and_returns_id`.
  - `test_log_progress_unknown_project_is_error_text` (starts with `"Lỗi:"`, store unchanged).
  - `test_log_progress_without_store_is_error_text`.
  - `test_get_worklog_lists_newest_first_with_next_steps`.
  - `test_get_worklog_empty_project_message`.
- [ ] **Step 2:** `cd backend && uv run pytest tests/test_mcp_server.py -q` → new tests FAIL.
- [ ] **Step 3:** Implement the two tools.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat(mcp): add log_progress and get_worklog tools`.

### Task 4: REST route `/api/v1/agent/worklog`

**Files:**
- Create: `backend/personal_kb/api/worklog.py`
- Modify: `backend/personal_kb/main.py` (`include_router(worklog.router)`)
- Test: `backend/tests/test_worklog_api.py`

**Interfaces:**
- Consumes: `agent_auth` from `personal_kb/api/agent.py`; `app.state.tool_context.worklog` and `.projects`; Task 1 validation.
- Produces:
  - `router = APIRouter(prefix="/api/v1/agent/worklog", tags=["worklog"], dependencies=[Depends(agent_auth)])`.
  - Dependency `get_worklog_store(request: Request) -> WorklogStore` (503 when `None`), overridable in tests.
  - `GET ?project=<str>&limit=<1..50, default 5>&kind=<str>` → `200 [{"id","project","kind","summary","next_steps","agent","session_id","branch","created_at"}]` (ISO-8601 `created_at`), unknown project → 422.
  - `POST` JSON body with `NewWorklogEntry` fields → `201` same object shape; validation error → 422 with the Vietnamese message.

- [ ] **Step 1: Write the failing tests** following `tests/test_agent_api.py` (`create_app(make_settings(dev_login=True, …))`, `app.dependency_overrides[get_worklog_store]`, `ASGITransport`):
  - `test_post_then_get_round_trip`, `test_post_unknown_kind_is_422`, `test_get_limit_over_50_is_422`, `test_no_store_is_503`.
- [ ] **Step 2:** `cd backend && uv run pytest tests/test_worklog_api.py -q` → FAIL.
- [ ] **Step 3:** Implement router and include it.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat(api): add agent worklog REST route`.

### Task 5: Deploy to kb-backend and verify live

**Files:**
- Modify: `docker-compose.yml` (backend: volume `./config:/app/config:ro`, env `PROJECTS_CONFIG=/app/config/projects.json`)

- [ ] **Step 1:** Edit compose; `docker compose config --quiet` → exit 0.
- [ ] **Step 2:** `docker compose up -d --build backend`; `curl -s localhost:8000/health` → `{"status":"ok"}`.
- [ ] **Step 3:** `curl -s -X POST localhost:8000/api/v1/agent/worklog -H 'Content-Type: application/json' -d '{"project":"Personal-KB","kind":"progress","summary":"worklog deployed","agent":"claude"}'` → 201 with an `id`; `curl -s 'localhost:8000/api/v1/agent/worklog?project=Personal-KB'` → contains `worklog deployed`.
- [ ] **Step 4:** Extend the scratch MCP probe (spawn `scripts/mcp_server.sh`, JSON-RPC `tools/list` then `tools/call get_worklog {"project":"Personal-KB"}`) → `log_progress` and `get_worklog` listed; the entry from Step 3 returned.
- [ ] **Step 5: Commit** `chore(infra): mount project map into kb-backend`.

### Task 6: `project_brief.py` — project resolution, git, worklog sections

**Files:**
- Create: `scripts/project_brief.py`
- Test: `backend/tests/test_project_brief.py` (loads the script with `importlib.util.spec_from_file_location`, path `Path(__file__).resolve().parents[2] / "scripts/project_brief.py"`)

**Interfaces:**
- Consumes: `config/projects.json` (default path: `<script dir>/../config/projects.json`); REST GET from Task 4 at `KB_API_URL` (env, default `http://localhost:8000`).
- Produces:
  - `load_projects(path: Path) -> dict[str, Project]` with `@dataclass(frozen=True) class Project: name: str; repo: Path; git_author: str` (`repo` = `expanduser().resolve()`).
  - `resolve_project(cwd: Path, projects: dict[str, Project]) -> Project | None` — `cwd.resolve()`, longest `repo` that equals cwd or is a parent (path-component match, not string prefix).
  - `git_section(project: Project, *, now: datetime) -> str` — `git -C <repo>` with `timeout=1.5`, `--author=<git_author>`, `--since=<now-7d>`; `""` on any failure.
  - `worklog_section(project: Project, *, base_url: str, timeout: float = 2.0) -> str` — `urllib.request`; on failure returns `"worklog: không truy cập được"`.
  - `redact(text: str) -> str` — replaces matches of the Review Focus #4 patterns with `[REDACTED]`; applied to every section.

- [ ] **Step 1: Write the failing tests** (`tmp_path` git repo created with `git init` + two commits using `-c user.email=dattruong19122003@gmail.com` and one by `other@example.com`; a local `http.server` thread for the worklog):
  - `test_resolve_project_subdirectory_and_symlink` (Review Focus 1, including a symlinked path and a sibling `repo2` that must not match).
  - `test_resolve_project_unmapped_is_none`.
  - `test_git_section_lists_branch_dirty_files_and_only_author_commits` (≤ 8 commits, ≤ 10 files, other author absent).
  - `test_git_section_not_a_repo_is_empty` and `test_git_section_git_missing_is_empty` (PATH without git) — Review Focus 5.
  - `test_worklog_section_formats_entries` (fake server returns 2 entries → both summaries and `next_steps`).
  - `test_worklog_section_down_or_slow_degrades` (closed port; server sleeping 3 s → returns within 2.5 s with the degraded line) — Review Focus 3.
  - `test_redact_masks_secrets` (each pattern in Review Focus 4).
- [ ] **Step 2:** `cd backend && uv run pytest tests/test_project_brief.py -q` → FAIL.
- [ ] **Step 3:** Implement those functions in `scripts/project_brief.py` (stdlib only; module docstring states usage).
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat(brief): resolve project and build git/worklog sections`.

### Task 7: `project_brief.py` — previous session, budget, output formats, CLI

**Files:**
- Modify: `scripts/project_brief.py`
- Test: `backend/tests/test_project_brief.py` (append)

**Interfaces:**
- Consumes: Task 6 functions.
- Produces:
  - `@dataclass(frozen=True) class Session: runtime: str; session_id: str; at: datetime; last_user: str; last_reply: str`.
  - `claude_last_session(repo: Path, *, root: Path = ~/.claude/projects, exclude: str = "") -> Session | None` — candidate dirs: every child of `root` whose name starts with `slug(repo)` where `slug` replaces `/` and `.` with `-`; only top-level `*.jsonl` (never `*/subagents/*`); newest by mtime, skipping `exclude`; last `type=="user"` line with `isMeta` false, `isSidechain` false and text content (string, or `text` blocks — not `tool_result`), last `type=="assistant"` text block; ignore `thinking`.
  - Transcripts are read **from the tail**: at most the last 512 KB of each file (seek, drop the first partial line). This session's jsonl is already 3.3 MB.
  - `agy_last_session(repo: Path, *, root: Path = ~/.gemini/antigravity-cli, exclude: str = "") -> Session | None` — `sqlite3` read-only URI on `conversation_summaries.db`: `nesting_depth = 0`, `parent_conversation_id = ''`, `agent_name = ''` (drops AGY `advisor` conversations), any `workspace_uris` entry (JSON list of `file://` URIs) whose path is the repo or inside it; newest `last_modified_time`; then `brain/<id>/.system_generated/logs/transcript.jsonl`: last `type=="USER_INPUT"` content (inner text of `<USER_REQUEST>…</USER_REQUEST>` if present), last `source=="MODEL" and type=="PLANNER_RESPONSE"` content; ignore `thinking`.
  - `build_brief(cwd: Path, *, runtime: str, session_id: str = "", now: datetime | None = None, projects_path: Path = …, base_url: str = …) -> str` — `""` when unmapped; header line `"PROJECT BRIEF — <project> (<repo>)"`; sections in spec order (worklog, git, "Phiên trước" from the *other* runtime, closing reminder line about `log_progress`); each transcript field ≤ 400 chars; whole result ≤ 2500 chars (trim the previous-session block first, then git); `redact` applied.
  - `main(argv: list[str] | None = None) -> int` — args `--cwd`, `--runtime {claude,agy}` (default `agy`), `--session-id`, `--format {text,claude-hook}`; when stdin is not a TTY and has JSON, take `cwd`/`session_id` (Claude payload) or `workspacePaths[0]`/`conversationId` (AGY payload); `claude-hook` prints `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":<brief>}}` or `{}` when empty; any exception → prints nothing (`{}` in hook format), returns 0. `if __name__ == "__main__": sys.exit(main())`.

- [ ] **Step 1: Write the failing tests** with fake roots under `tmp_path`:
  - `test_claude_last_session_skips_meta_sidechain_tool_results_and_subagents`.
  - `test_claude_last_session_includes_subdirectory_slug_and_excludes_current`.
  - `test_agy_last_session_picks_main_conversation_in_repo` (sqlite fixture with a nested one, one in another repo, one in a subdirectory).
  - `test_transcript_malformed_partial_and_huge_lines` (Review Focus 2: invalid JSON line, truncated last line, a 1 MB content line → no exception, field ≤ 400 chars).
  - `test_build_brief_other_runtime_only` (runtime `agy` shows the Claude session, not the AGY one).
  - `test_build_brief_budget_2500` (oversized inputs → ≤ 2500 chars, header and worklog kept).
  - `test_build_brief_unmapped_is_empty`.
  - `test_main_claude_hook_format_and_exit_zero_on_error` (bad projects path → `{}` and return 0).
  - `test_worklog_secret_is_redacted_in_brief` (Review Focus 4 via a worklog entry).
  - `test_agy_advisor_conversation_is_ignored` (`agent_name='advisor'` row newer than the main one → main one chosen).
  - `test_large_transcript_tail_read_is_fast` (8 MB fake jsonl → `claude_last_session` < 0.3 s and returns the last turn).
  - `test_script_runs_under_system_python` — `subprocess.run(["/usr/bin/python3", SCRIPT, "--cwd", str(tmp_path), "--format", "claude-hook"])` → returncode 0, stdout `{}` (catches 3.10+ syntax that the 3.11 venv would hide).
- [ ] **Step 2:** `cd backend && uv run pytest tests/test_project_brief.py -q` → new tests FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Same command → PASS; then real run: `/usr/bin/python3 scripts/project_brief.py --cwd ~/Project/personal-kb --runtime agy` → brief shows this Claude session in "Phiên trước", ≤ 2500 chars.
- [ ] **Step 4b:** Create `~/Project/_continuity-bench` (`git init`, one commit by `dattruong19122003@gmail.com`) and add `"Continuity-Bench": {"repo": "~/Project/_continuity-bench", …}` to `config/projects.json` for Tasks 8–11 (not committed; removed in Task 11). Restart `kb-backend` so `ToolContext.projects` includes it.
- [ ] **Step 5: Commit** `feat(brief): add previous-session block, budget and CLI`.

### Task 8: Install the Claude SessionStart hook (personal config)

**Files:**
- Modify (outside repo): `~/.claude/settings.json`
- Create: `docs/agent-continuity/config-changes.log`

- [ ] **Step 1:** Create the log; first line records the 2026-10-24 desktop change: `2026-10-24T20:58:29+07:00 | ~/Library/Application Support/Claude/claude_desktop_config.json | backup: claude_desktop_config.json.bak-20261024-205829 | mcpServers.personal-kb → /bin/bash scripts/mcp_server.sh + env.PATH | undo: cp <backup> <file>`.
- [ ] **Step 2:** Back up `~/.claude/settings.json`; append (do not replace) a SessionStart entry with `"matcher": "startup|resume|clear|compact"` running `/usr/bin/python3 /Users/ryantruong/Project/personal-kb/scripts/project_brief.py --runtime claude --format claude-hook`, `timeout: 5`. Keep the Orca hooks untouched (verify by JSON-diffing every other key against the backup). Log the change.
- [ ] **Step 2b:** `claude mcp list` shows no `personal-kb` (checked 2026-10-24), so `claude -p` cannot call `log_progress`. Run `claude mcp add --scope user personal-kb -- /bin/bash /Users/ryantruong/Project/personal-kb/scripts/mcp_server.sh` (back up `~/.claude.json` first, log it); `claude mcp list` → `personal-kb … ✓ Connected`.
- [ ] **Step 3:** Verify: in `~/Project/_continuity-bench`, `claude -p "Trả lời một dòng: dòng tiêu đề PROJECT BRIEF trong ngữ cảnh của bạn là gì? Không thấy thì ghi KHONG_THAY."` → output contains `PROJECT BRIEF — Continuity-Bench`. In `~/Project/MyEQ` → `KHONG_THAY`. Also read the new transcript's `entrypoint` for that `-p` run and note it in the log: if it differs from `claude-desktop`, add an `entrypoint` filter to `claude_last_session` with a test.
- [ ] **Step 4: Commit** `docs(agent-continuity): add config change log`.

### Task 9: Global rules carve-out and AGY read rule (personal config)

**Files:**
- Modify (outside repo): `~/.agents/GLOBAL.md`, `~/.kiro/steering/GLOBAL.md`
- Modify: `integrations/rules/personal-kb-grounding.md`
- Modify: `docs/agent-continuity/config-changes.log`

- [ ] **Step 0:** Check how AGY treats the read-only command `/usr/bin/python3 ~/Project/personal-kb/scripts/project_brief.py …` with its default flags: run `agy -p "chạy lệnh: /usr/bin/python3 ~/Project/personal-kb/scripts/project_brief.py --runtime agy --cwd ~/Project/_continuity-bench rồi in dòng đầu" --print-timeout 120s` and see whether it runs, is denied, or waits for approval. If it needs approval, find AGY's command allowlist in `~/.gemini/config/` and allow exactly that command prefix (back up, log). Record the flags Ryan normally uses with `agy` and use the same flags in Task 11.
- [ ] **Step 1:** Back up both outside files. In `GLOBAL.md` section "Quy tắc Tra cứu Tri thức…", rewrite item 4's first bullet so "không tự ý chỉnh sửa" covers **requirement trong `knowledge/`** only, and add a new item "Worklog (vùng AI tự ghi)" stating, in Vietnamese: worklog được ghi thẳng qua MCP `log_progress`, không cần proposal; gọi khi xong bước đáng kể, khi ra quyết định, khi gặp cạm bẫy, và trước khi kết thúc/bàn giao; "cập nhật tiến độ" nghĩa là `log_progress`; ở lượt đầu của hội thoại mới trong một repo, nếu ngữ cảnh chưa có dòng `PROJECT BRIEF`, chạy `/usr/bin/python3 ~/Project/personal-kb/scripts/project_brief.py --runtime agy --cwd "$PWD"` và đọc kết quả trước khi làm. Mirror the same text in `integrations/rules/personal-kb-grounding.md` and copy `GLOBAL.md`'s edited sections to the Kiro steering file. Log each file.
- [ ] **Step 2:** Verify Claude still reads it: `claude -p "Theo hướng dẫn của bạn, khi người dùng nói 'cập nhật tiến độ' bạn gọi tool nào?"` → mentions `log_progress`.
- [ ] **Step 3:** Verify AGY: `log_progress` an entry with `next_steps` = `"kiểm tra marker AC-<random>"` for Continuity-Bench, then in `~/Project/_continuity-bench` run `agy -p "tiếp tục" --print-timeout 180s` (flags from Step 0) → output mentions the marker.
- [ ] **Step 4: Commit** `docs(rules): scope Human Gate to requirements and add worklog rule`.

### Task 10: AGY plugin injection experiment (time-boxed 30 minutes)

**Files:**
- Create (outside repo, only if it works): a local AGY plugin dir with `hooks.json` at its root; installed via `agy plugin install <dir>`.

- [ ] **Step 1:** Build a throwaway plugin whose `PreInvocation` hook runs a script printing `{"userMessage": <brief>}` only when `invocationNum == 0 and initialNumSteps == 1`, else `{}`. Back up/log any config the install touches.
- [ ] **Step 2:** Test in both `agy -p` and an interactive `agy` session in `~/Project/_continuity-bench`: ask for the `PROJECT BRIEF` header line without tools. The interactive run is driven through a Terminal panel tab (`run_in_terminal` / `read_terminal`); if that cannot drive AGY's TUI, ask Ryan to run it.
- [ ] **Step 3:** If both show it: keep the plugin, make it call `project_brief.py --runtime agy` with the hook payload on stdin, and log it. If not within 30 minutes: uninstall, restore, log the removal, and record the result in the benchmark report. Either way Task 9's rule stays.

### Task 11: Benchmark and acceptance report

**Files:**
- Create: `scripts/bench_agent_continuity.py`
- Create: `docs/agent-continuity/benchmark-report.html`

**Interfaces:**
- Consumes: `scripts/project_brief.py`, REST/MCP from Tasks 3–5, `claude` and `agy` CLIs.

- [ ] **Step 1:** Write `bench_agent_continuity.py` (stdlib) that measures what it can measure automatically and writes raw results to JSON: brief latency (20 runs per mapped repo, backend up, then `docker stop kb-backend` and 20 more, then `docker start kb-backend`), brief size per repo, exit codes, and the secret-redaction check (scenario 8 of the spec).
- [ ] **Step 2:** Run it; thresholds: p95 < 3 s, size ≤ 2500, all exit 0, 0 leaks.
- [ ] **Step 3:** Run the CLI scenarios in `~/Project/_continuity-bench` and record each run's prompt, output excerpt, and pass/fail. Rows marked **[Ryan]** need an interactive session: drive them through a Terminal panel tab first; only if the TUI cannot be driven, list them for Ryan with exact steps instead of marking them NOT_RUN silently.
  - Claude auto-load: 3 × `claude -p` new sessions + **[Ryan]** one `/compact` in an interactive `claude` session (4/4).
  - AGY rule: `agy -p "tiếp tục"` ×10 (≥ 9/10) + **[Ryan]** 3 interactive `agy` sessions (3/3).
  - Spec scenarios 1, 2, 3 ×3 each (9/9) using `-p` runs; scenario 6 (`~/Project/MyEQ`, unmapped) once.
- [ ] **Step 4:** Write `benchmark-report.html` (standalone, dark/light tokens like the spec page, copy buttons on commands): results table with thresholds, raw numbers, AGY rate and any known limitation, which rows Ryan ran, the `agy`/`claude` flags used, commands to re-run.
- [ ] **Step 5:** Cleanup: remove `Continuity-Bench` from `config/projects.json` (`git diff config/projects.json` → empty), restart `kb-backend`, leave `~/Project/_continuity-bench` on disk but note it in the log; append the cleanup to `docs/agent-continuity/config-changes.log`. Run `/usr/bin/python3 scripts/project_brief.py --cwd ~/Project/personal-kb --runtime agy` → "Phiên trước" is a real session, not a bench run.
- [ ] **Step 6: Commit** `test(agent-continuity): add benchmark and acceptance report`.
