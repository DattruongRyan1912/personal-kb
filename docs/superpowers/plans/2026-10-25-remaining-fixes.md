# Remaining Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the issues left open on 2026-10-25: search quality (no re-ranker, unmeasured, typos, a fallback edge case), worklog redaction that masks ordinary text, silent setup drift (stale bind mount, overwritten desktop MCP config, re-ranker down), Postgres tests skipped by default, mislabeled specs, and lint debt.

**Architecture:** Each fix stays in the stack already running (Postgres FTS + pgvector, the TEI-compatible re-ranker API, stdlib host scripts). Search changes are measured by a fixed eval set run against the live backend, before and after, never by grepping the specs that produced the labels. Requirement files in `knowledge/` change only through `propose_knowledge_update` and Ryan's approval.

**Tech Stack:** Python 3.11 (backend, uv), Postgres 17 + pgvector + pg_trgm + unaccent, FastAPI, FlagEmbedding (local re-ranker, `local-reranker` group), macOS launchd, stdlib Python 3.9 for host scripts.

**Spec:** none written; this plan argues from the session of 2026-10-25 (worklog #24–#30 of Personal-KB). Rulings made from it are provisional.

## Global Constraints

- Never print credentials, tokens or `.env` values; derive `POSTGRES_URL` from the container into a `chmod 600` file outside the repo.
- No AI attribution in commits (no `Co-Authored-By`, no "Generated with").
- No commit, push or merge without Ryan's go-ahead per batch.
- `knowledge/*.md` requirement files: AI never edits them; only `propose_knowledge_update`, approved by Ryan.
- Personal config edits (`~/Library/LaunchAgents`, `~/.docker/config.json`, Claude config): backup first, one line in `docs/agent-continuity/config-changes.log` (`timestamp | path | backup | change | undo`).
- Host scripts in `scripts/` run on `/usr/bin/python3` 3.9.6, stdlib only.
- `backend/personal_kb/services/redaction.py` and `scripts/project_brief.py::_REDACTIONS` stay identical (`test_redaction_patterns_match_host_script`).
- Every task ends with the full suite green with Postgres: `scripts/test.sh` (Task 1), and `log_progress` for Personal-KB.

## Review Focus

- A search question with no answer in any spec must still return nothing useful-looking: the any-word fallback and typo correction must not turn "no answer" into confident noise (Tasks 4–5 test an unrelated query).
- The re-ranker down must keep search working (today's behaviour) and be visible, not silent (Task 3 logs it, Task 7 reports it).
- Redaction narrowed for `primary key:` must still mask every secret form the current tests list (Task 6 keeps them all).
- `doctor` must never print a secret or a full config file, only verdicts (Task 7 test).
- Lint cleanup must change no behaviour: full suite and the search eval before and after are equal (Task 9).

---

### Task 1: One command for the full suite with Postgres

**Files:**
- Create: `scripts/test.sh`
- Modify: `README.md` (section "📚 Tài liệu kỹ thuật": one line on running tests)

**Interfaces:**
- Produces: `scripts/test.sh [pytest args…]`, used by every later task.

- [ ] **Step 1:** Write `scripts/test.sh` (bash, `set -euo pipefail`): read `POSTGRES_URL` from `docker exec kb-backend printenv POSTGRES_URL`, replace the host part with `127.0.0.1:5434` (`sed -E 's#@[^/]+/#@127.0.0.1:5434/#'`), write it to `"${TMPDIR:-/tmp}/personal-kb-test.env"` with `umask 077`, then `cd backend && uv run --env-file ../.env --env-file "$envfile" env POSTGRES_REQUIRED=1 pytest -q "$@"`. If `kb-backend` is not running, exit 1 with `kb-backend is not running: docker compose up -d`.
- [ ] **Step 2:** Run `scripts/test.sh`. Expected: `612 passed`, and no `POSTGRES_URL not set` skip (`scripts/test.sh -rs | grep -c "POSTGRES_URL not set"` → `0`).
- [ ] **Step 3:** Commit `test: one script runs the suite against the local Postgres`.

### Task 2: A fixed search eval set

**Files:**
- Create: `backend/evals/search_cases.json`
- Create: `backend/scripts/eval_search.py`
- Test: `backend/tests/test_eval_search.py`

**Interfaces:**
- Produces: `python -m scripts.eval_search [--cases evals/search_cases.json] [--json out.json]` run inside `kb-backend`; prints one line per case and `HIT@5 n/N  MRR x.xx`. Pure helpers: `hit_at(ids: list[str], want: list[str], k: int) -> bool`, `reciprocal_rank(ids: list[str], want: list[str]) -> float`.

- [ ] **Step 1:** Write the cases file: a list of `{"query", "project", "want": [spec ids], "kind": "accent|no-accent|prose|typo|keyword|off-topic"}`. Start from the 13 queries of 2026-10-25 (scratchpad `eval.py`) with their original labels, plus: 3 typo cases (`"chấm cộng"`, `"bảo hiêm xã hội"`, `"quyết toán thuê"`), 2 off-topic cases with `"want": []` (`"công thức nấu phở"`, `"giá bitcoin hôm nay"`). Each case's `want` is the spec that **answers** the question, chosen by reading the spec section, not by keyword counts.
- [ ] **Step 2:** Failing tests: `hit_at(["A","B"], ["B"], 1) is False`, `hit_at(["A","B"], ["B"], 2) is True`, `reciprocal_rank(["A","B"], ["B"]) == 0.5`. Off-topic cases (`want == []`) count as a hit only when nothing is returned: `hit_at([], [], 5) is True`, `hit_at(["A"], [], 5) is False`, `reciprocal_rank([], []) == 1.0`, `reciprocal_rank(["A"], []) == 0.0`.
- [ ] **Step 3:** Implement the helpers and the runner (uses `services(get_settings())`, `retriever.search(query, project_id=project)`; spec ids in result order, deduplicated).
- [ ] **Step 4:** Rebuild `kb-backend` (`docker compose up -d --build backend`), run the eval, save to `docs/search-eval/2026-10-25-baseline.json`. Expected: the 13 original cases give 9/13 (as on 2026-10-25).
- [ ] **Step 5:** **Ryan reviews the labels** in `search_cases.json` (the four misses of 2026-10-25 may be wrong labels: "nghỉ phép năm", "đi muộn về sớm", "hợp đồng lao động", "BHXH"). Relabel only on his answer; rerun and save the baseline again.
- [ ] **Step 6:** Commit `test(search): fixed eval set and runner`.

### Task 3: Run the re-ranker

The backend calls `RERANKER_URL=http://host.docker.internal:8081`; nothing listens there, so every search skips re-ranking (`HybridRetriever.search` returns the fused list unranked). `backend/scripts/local_reranker.py` serves the TEI `/rerank` API on the Mac GPU; the model `BAAI/bge-reranker-v2-m3` is already in `~/.cache/huggingface/hub`.

**Files:**
- Create: `integrations/launchd/com.personal-kb.reranker.plist` (versioned copy)
- Install: `~/Library/LaunchAgents/com.personal-kb.reranker.plist` (personal config: backup none needed, log line)
- Modify: `README.md` (how to start/stop the re-ranker)

- [ ] **Step 1:** `cd backend && uv sync --group local-reranker`; start by hand `uv run --group local-reranker python -m scripts.local_reranker --port 8081`; check `curl -s 127.0.0.1:8081/rerank -H 'content-type: application/json' -d '{"query":"lương","texts":["bảng lương","nghỉ phép"]}'` returns two scores, the first higher.
- [ ] **Step 2:** Write the plist: `ProgramArguments` = absolute `uv` path, `run --directory /Users/ryantruong/Project/personal-kb/backend --group local-reranker python -m scripts.local_reranker --port 8081`; `RunAtLoad` true, `KeepAlive` true, logs to `~/Library/Logs/personal-kb-reranker.log`. Install with `launchctl bootstrap gui/$(id -u) <plist>`; log the change.
- [ ] **Step 3:** Run the eval (Task 2). Save `docs/search-eval/2026-10-25-reranker.json`. Expected: HIT@5 ≥ baseline; record per-case changes. If lower, stop and report (the re-ranker is then a regression, not a fix).
- [ ] **Step 4:** Check latency: `docker logs kb-backend | grep "rerank .* ms"` for the eval run; record p50. Target < 2 s per search.
- [ ] **Step 5:** Commit `feat(search): run the bge re-ranker locally under launchd`.

### Task 4: The any-word fallback keeps exclusions out

`fts_search_sql(any_word=True)` replaces ` & ` with ` | ` in the tsquery text, so `-từ` (websearch exclusion `!'tu'`) becomes `| !'tu'`, which matches almost every chunk.

**Files:**
- Modify: `backend/personal_kb/infrastructure/postgres/pg_vector_store.py` (`search_fts`)
- Test: `backend/tests/contract/test_vector_store_contract.py`

- [ ] **Step 1:** Failing test `test_keyword_fallback_ignores_excluded_words` (postgres only): ingest HR-A "Hệ số làm thêm giờ." and HR-B "Nghỉ phép năm."; `fts(store, "hệ số lương -phép")` == `["HR-A"]` (AND fails on "lương"; the fallback must not match HR-B through `!phép`).
- [ ] **Step 2:** Implement: for the `any_word` pass only, drop query tokens starting with `-` (`" ".join(w for w in query.split() if not w.startswith("-"))`); if nothing is left, return `[]`.
- [ ] **Step 3:** `scripts/test.sh tests/contract` → pass; commit `fix(search): the any-word fallback drops excluded words`.

### Task 5: Typo correction (only if the eval needs it)

- [ ] **Step 0:** After Task 3, read the 3 typo cases of the eval. If all hit@5, skip this task and write that ruling in the worklog.
- [ ] **Step 1 (otherwise), Files:** Modify `backend/personal_kb/infrastructure/postgres/schema.sql` (materialized view `chunk_lexemes(word)` from `ts_stat('SELECT tsv FROM chunks WHERE valid_to IS NULL')`, `gin (word gin_trgm_ops)`), `pg_vector_store.py` (`refresh_lexemes()`, called at the end of `apply_revision`; `correct_query(query) -> str`), test in the contract file.
- [ ] **Step 2:** Failing tests: after ingesting "Chấm công theo ca", `correct_query("cham cong")` keeps the words (known); `correct_query("cham cpng")` == `"cham cong"`; `correct_query("pho bo")` with no close word (similarity < 0.5) returns it unchanged; off-topic query still returns `[]` from `search_fts`.
- [ ] **Step 3:** Implement: unaccent + lowercase each query word; a word not in `chunk_lexemes` is replaced by the most similar one with `similarity(word, $1) >= 0.5`, else kept. Correction applies only to the second (any-word) pass.
- [ ] **Step 4:** Eval: typo cases improve, off-topic cases stay empty, others unchanged. Commit `feat(search): correct misspelt keywords against the indexed vocabulary`.

### Task 6: Redaction stops masking ordinary text

`redact("primary key: chunk_key")` → `primary key: [REDACTED]`; `"monkey: banana"` and `"the key: idea"` are masked too, because the name pattern is `[A-Za-z0-9_\-]*(?:password|passwd|token|secret|key)`. And `validate_entry` checks lengths after redaction, which can grow the text.

**Files:**
- Modify: `backend/personal_kb/services/redaction.py`, `scripts/project_brief.py` (same pattern), `backend/personal_kb/services/worklog.py`
- Test: `backend/tests/test_project_brief.py`, `backend/tests/test_worklog.py`

- [ ] **Step 1:** Failing tests in `test_project_brief.py`: `pb.redact(t) == t` for `"primary key: chunk_key"`, `"monkey: banana"`, `"the key: idea is X"`, and as a guard `"token budget: 2500"` (passes today; must keep passing). `token: abc` stays masked. All existing secret cases (`test_redact_masks_secrets`, `test_redact_env_style_and_json`) unchanged.
- [ ] **Step 2:** Failing test in `test_worklog.py`: a summary of exactly 2000 chars containing `password=x` is accepted (length is checked on the text as written).
- [ ] **Step 3:** Implement the name group `(?i)\b((?:[A-Za-z0-9]+[_\-])*(?:password|passwd|token|secret)|(?:[A-Za-z0-9]+[_\-])+key|apikey)` (bare `key` needs a prefix such as `api_`, `x-api-`, `SECRET_`), same in both files; in `validate_entry`, check lengths before redacting.
- [ ] **Step 4:** `scripts/test.sh` → pass (sync test included); commit `fix(worklog): redact secret names, not every word ending in key`.

### Task 7: `doctor` reports setup drift

Three silent failures of 2026-10-25: `/app/config` empty after a re-created bind-mount source; `claude_desktop_config.json` rewritten by the app to the CyberOS server; the re-ranker down.

**Files:**
- Create: `scripts/doctor.py` (stdlib, `/usr/bin/python3`)
- Test: `backend/tests/test_doctor.py`

**Interfaces:**
- Produces: `doctor.py [--json]`, exit 0 when every check passes, 1 otherwise; one line per check: `OK|FAIL <name>: <verdict>`. Checks are functions returning `(ok: bool, verdict: str)`, injectable for tests.

- [ ] **Step 1:** Failing tests with fakes (no Docker): `check_desktop_mcp(config_dict)` FAIL when `mcpServers.personal-kb.args` does not end with `personal-kb/scripts/mcp_server.sh`, verdict names the found directory only; `check_project_map(listing)` FAIL on an empty listing with verdict `config/ mount is stale: docker compose up -d --force-recreate backend`; `check_reranker(status)` FAIL on connection refused; no verdict ever contains `=` followed by a value from the env (test with a fake env holding `sk-…`).
- [ ] **Step 2:** Implement checks: backend `/health`; `docker exec kb-backend ls /app/config` non-empty; desktop config `personal-kb` points at this repo; `~/.claude.json` `mcpServers.personal-kb` likewise; re-ranker `POST /rerank` on `127.0.0.1:8081` answers; documents count = number of `knowledge/**/*.md` outside `proposals/`.
- [ ] **Step 3:** Run it live: all OK. Add one line to `README.md` and to `docs/architecture.md` §4. Commit `feat(ops): doctor script for stack and agent-config drift`.

### Task 8: Specs with the wrong project

`CYBEROS-01` and `CYBEROS-02` have no `project` in their frontmatter (ingest files them under Personal-KB); `mynotch-context` declares `project: mynotch`. Requirement files: proposals only.

- [ ] **Step 1:** Ask Ryan which project `CYBEROS-01` ("Kiến trúc Memory Fabric…") and `CYBEROS-02` ("Giao thức Tích hợp AI Agent & MCP") belong to; their titles describe Personal-KB's own architecture, so the answer is not obvious.
- [ ] **Step 2:** `search_knowledge` for duplicates, then `propose_knowledge_update` for each change (frontmatter `project:` only). Report the proposal ids; Ryan approves with `Duyệt proposal <id>`.
- [ ] **Step 3:** After approval: `scripts/ingest.sh`; check `chunks` project counts and `list_specs`. No commit needed if the approval flow commits; otherwise commit `docs(kb): file … under …` on Ryan's go-ahead.

### Task 9: Lint debt

`ruff check .` reports errors in files untouched today (28 auto-fixable, plus E501, B008, B904, F841, F821…); `ruff format --check .` lists 24 files.

**Files:** whatever ruff reports under `backend/`; `backend/pyproject.toml` (`[tool.ruff.lint.flake8-bugbear] extend-immutable-calls = ["fastapi.Depends", "fastapi.File", "fastapi.Form", "fastapi.Query"]`).

- [ ] **Step 1:** Record the before state: `scripts/test.sh` result and the eval JSON.
- [ ] **Step 2:** `uv run ruff check --fix .`, `uv run ruff format .`; add the bugbear config; fix the rest by hand (wrap long lines, `raise … from exc`, remove unused locals). No logic change: a fix that would change behaviour is listed, not made.
- [ ] **Step 3:** `uv run ruff check . && uv run ruff format --check .` → clean; `scripts/test.sh` → same counts; eval → identical JSON. Commit `style: clear ruff findings across the backend`.

### Ryan's own steps (not delegated)

- [ ] Rotate the API keys in `.env` (they appeared in tool output on 2026-10-24), then `docker compose up -d backend`.
- [ ] Docker builds fail on `error getting credentials` because `~/.docker/config.json` has `"credsStore": "desktop"` and the helper fails. Either sign in to Docker Desktop, or allow removing that key (backup + log; Claude can do it on a yes).
