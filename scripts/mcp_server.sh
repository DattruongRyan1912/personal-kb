#!/bin/bash
# Personal-KB MCP server over stdio, for Claude Code, Claude desktop and AGY.
#
# It runs on the host from backend/.venv rather than through `docker exec` into kb-backend: that channel died with the
# container, and the clients never reopen a stdio server, so every open session lost the KB whenever kb-backend
# restarted. The server reaches Postgres, Redis, Ollama and the re-ranker on their host ports, with the settings the
# backend service gets in docker-compose.yml, read from the repo .env (tests/test_mcp_launcher.py keeps them in step).
# stdout is the JSON-RPC channel: nothing else may print to it.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${KB_ENV_FILE:-$DIR/.env}"
PYTHON="${KB_MCP_PYTHON:-$DIR/backend/.venv/bin/python}"
cd "$DIR/backend"

if [ ! -x "$PYTHON" ]; then # no host venv yet (cd backend && uv sync): the server inside the container still works
  exec docker exec -i kb-backend python -m personal_kb.mcp.cli
fi

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
on_host() { printf '%s' "${1//host.docker.internal/127.0.0.1}"; }

export POSTGRES_URL="postgresql://${PG_USER:-kb_user}:${PG_PASSWORD:-kb_secret_password_2026}@127.0.0.1:${PG_PORT:-5434}/${PG_DATABASE:-knowledge_db}"
export POSTGRES_SCHEMA=public
export REDIS_URL="redis://127.0.0.1:${REDIS_PORT:-6380}/0"
RERANKER_URL="$(on_host "${RERANKER_URL:-http://127.0.0.1:8081}")"
EMBEDDING_BASE_URL="$(on_host "${EMBEDDING_BASE_URL:-http://127.0.0.1:11434/v1}")"
export RERANKER_URL EMBEDDING_BASE_URL
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}"
export LLM_MODEL="${LLM_MODEL:-deepseek-chat}"
export LLM_MODEL_THOROUGH="${LLM_MODEL_THOROUGH:-deepseek-chat}"
export LLM_REASONING_EFFORT="${LLM_REASONING_EFFORT:-none}"
export EMBEDDING_API_KEY="${EMBEDDING_API_KEY:-ollama}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-bge-m3}"
export EMBEDDING_DIMENSIONS="${EMBEDDING_DIMENSIONS:-1024}"
export AGENT_READ_SPECS="${AGENT_READ_SPECS:-false}"
export AGENT_MAX_TOOL_CALLS="${AGENT_MAX_TOOL_CALLS:-12}"
export SUPABASE_URL=http://localhost:54321
export SUPABASE_JWT_SECRET="${SUPABASE_JWT_SECRET:-dev-secret-jwt-key-for-standalone-kb-2026}"
export PROJECTS_CONFIG="$DIR/config/projects.json"
export GRAPH_SEARCH="${GRAPH_SEARCH:-false}"
export PYTHONUNBUFFERED=1

exec "$PYTHON" -m personal_kb.mcp.cli
