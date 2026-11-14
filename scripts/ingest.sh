#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

echo "=== Ingesting knowledge documents into Vector Database ==="
if docker ps --format '{{.Names}}' | grep -q "^kb-backend$"; then
  echo "Running ingestion inside kb-backend container..."
  docker exec kb-backend python -m scripts.ingest_sdd_to_vector /app/knowledge
else
  echo "Running ingestion via local host Python environment..."
  if [ -f "$DIR/.env" ]; then
    set -a
    . "$DIR/.env"
    set +a
  fi
  on_host() { printf '%s' "${1//host.docker.internal/127.0.0.1}"; }

  export POSTGRES_URL="postgresql://${PG_USER:-kb_user}:${PG_PASSWORD:-kb_secret_password_2026}@127.0.0.1:${PG_PORT:-5434}/${PG_DATABASE:-knowledge_db}"
  export POSTGRES_SCHEMA=public
  export REDIS_URL="redis://127.0.0.1:${REDIS_PORT:-6380}/0"
  RERANKER_URL="$(on_host "${RERANKER_URL:-http://127.0.0.1:8081}")"
  EMBEDDING_BASE_URL="$(on_host "${EMBEDDING_BASE_URL:-http://127.0.0.1:11434/v1}")"
  export RERANKER_URL EMBEDDING_BASE_URL
  export SUPABASE_URL=http://localhost:54321
  export SUPABASE_JWT_SECRET="${SUPABASE_JWT_SECRET:-dev-secret-jwt-key-for-standalone-kb-2026}"
  export EMBEDDING_API_KEY="${EMBEDDING_API_KEY:-ollama}"
  export EMBEDDING_MODEL="${EMBEDDING_MODEL:-bge-m3}"
  export EMBEDDING_DIMENSIONS="${EMBEDDING_DIMENSIONS:-1024}"
  export PROJECTS_CONFIG="$DIR/config/projects.json"

  cd backend
  ./.venv/bin/python -m scripts.ingest_sdd_to_vector ../knowledge
fi

echo "=== Ingestion completed successfully! ==="
