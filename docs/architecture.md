# Architecture

Personal-KB is a local knowledge base for AI agents. Requirements live as Markdown in `knowledge/` and change only
through human-approved proposals; agent progress lives in an AI-writable worklog. Agents reach both over MCP; people
use the web portal. Everything runs on one machine with Docker.

## 1. Runtime stack

All published ports bind to `127.0.0.1`. Embeddings come from Ollama on the host (`bge-m3`, 1024 dims); the chat
model is any OpenAI-compatible API (`OPENAI_BASE_URL`, default DeepSeek).

```mermaid
flowchart LR
  subgraph host[Host]
    ollama[Ollama bge-m3]
    kdir[(knowledge/ md)]
    cfg[(config/projects.json)]
  end
  subgraph compose[docker compose: personal-kb]
    fe[kb-frontend<br/>Next.js :3000]
    be[kb-backend<br/>FastAPI :8000]
    pg[(kb-postgres<br/>pgvector :5434)]
    rd[(kb-redis :6380)]
  end
  fe -->|REST| be
  be --> pg
  be --> rd
  be -->|embeddings| ollama
  kdir -. ro mount .-> be
  cfg -. ro mount .-> be
```

## 2. How agents use it (MCP)

Claude Code and Antigravity (AGY) start the MCP server over stdio with `scripts/mcp_server.sh`, which runs
`python -m personal_kb.mcp.cli` on the host from `backend/.venv`, reaching Postgres, Redis, Ollama and the re-ranker on
their host ports with the backend's compose settings. It used to run inside `kb-backend` through `docker exec`, and
every open session lost MCP whenever that container restarted, since the clients never reopen a stdio server. Without
`backend/.venv` it still falls back to `docker exec` (doctor warns). Tools share one `ToolContext` (retriever,
document store, worklog store, project list).

```mermaid
sequenceDiagram
  participant A as Agent
  participant M as MCP (kb-backend)
  participant S as Stores (Postgres)
  A->>M: search_knowledge / get_spec_content
  M->>S: hybrid search, documents
  S-->>M: chunks + spec ids
  M-->>A: quotes with [SPEC-ID]
  A->>M: propose_knowledge_update
  M-->>A: PENDING proposal (human gate)
  A->>M: log_progress / get_worklog
  M->>S: worklog_entries (append-only)
```

## 3. Requirements: ingest and approval

`knowledge/` is the source of truth. Ingestion is idempotent: only changed chunks are embedded, removed chunks are
closed, not deleted. A proposal changes a spec only after a person approves it (`/approvals` or
`scripts/manage_proposals.py`).

```mermaid
flowchart TD
  md[knowledge/*.md] --> ing[scripts/ingest.sh]
  ing --> chunk[chunk by headings]
  chunk --> emb[embed via Ollama]
  emb --> db[(chunks + documents)]
  agent[Agent] -->|propose_knowledge_update| prop[(knowledge/proposals)]
  prop --> gate{Ryan approves?}
  gate -->|yes| patch[patch spec md] --> ing
  gate -->|no| rej[rejected]
```

## 4. Agent continuity: worklog and project brief

At session start each agent gets a short brief built on the host by `scripts/project_brief.py` (stdlib, runs on
`/usr/bin/python3`): recent worklog entries, live git state, and the other runtime's last session. Claude loads it
through a SessionStart hook; AGY through the `kb-brief-injector` plugin (`integrations/agy-brief-plugin/`). The brief
is framed as reference data, not instructions, and secrets are redacted on write and on read.

```mermaid
flowchart TD
  start[Session starts in a mapped repo] --> hook{Runtime}
  hook -->|Claude| ss[SessionStart hook]
  hook -->|AGY| pi[PreInvocation plugin]
  ss --> pb[project_brief.py]
  pi --> pb
  pb --> wl[GET /api/v1/agent/worklog]
  pb --> git[git status + log]
  pb --> tr[other runtime transcript]
  pb --> brief[PROJECT BRIEF <= 2500 chars]
  brief --> ctx[injected into context]
  ctx --> work[agent works] --> lp[log_progress] --> wl
```

Writing the worklog is not left to the prompt alone: agents skipped it in most sessions that changed code. In
Claude Code and AGY (the kb-brief-injector plugin) a `Stop` hook (`scripts/worklog_guard.py`) holds a turn that edited files or committed in a mapped repo
without calling `log_progress`, once, asking for the entry and for a proposal if a spec went stale; if the agent stops
again without logging, the hook writes a minimal `[tự động]` entry itself through the worklog API.

When an agent sees stale or sample data, run `/usr/bin/python3 scripts/doctor.py`: it checks the backend, the
`config/` bind mount, both Claude MCP configs, the document count and the re-ranker.

Design and acceptance: `docs/superpowers/specs/2026-10-24-agent-continuity-design.html`,
`docs/agent-continuity/benchmark-report.html`.
