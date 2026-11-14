#!/bin/bash
# scripts/auto_ingest_hook.sh: Automatic background vector ingestion on knowledge commits.
# Triggered by .git/hooks/post-commit. Runs asynchronously in background.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

LOG_FILE="$REPO_DIR/.git/auto_ingest.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# 1. Identify changed markdown specs and code files in HEAD
CHANGED_SPECS="$(git diff-tree -r --no-commit-id --name-only HEAD 2>/dev/null | grep -E '^knowledge/.*\.md$' | grep -v '^knowledge/proposals/' || true)"
CHANGED_CODE="$(git diff-tree -r --no-commit-id --name-only HEAD 2>/dev/null | grep -E '\.(py|ts|tsx|js|swift|dart|go|rs|cs)$' || true)"

if [ -z "$CHANGED_SPECS" ] && [ -z "$CHANGED_CODE" ]; then
  # No knowledge specs or code files affected in this commit
  exit 0
fi

# 2. Incremental CodeGraph AST Indexing if code files changed
if [ -n "$CHANGED_CODE" ] && [ -d "$REPO_DIR/.codegraph" ] && [ -x "$REPO_DIR/backend/.venv/bin/python" ]; then
  log "Detected source code changes in commit $(git rev-parse --short HEAD 2>/dev/null), running incremental CodeGraph AST index..."
  PYTHONPATH="$REPO_DIR/backend" "$REPO_DIR/backend/.venv/bin/python" -c "
from pathlib import Path
from personal_kb.services.code_graph_indexer import CodeGraphIndexer
res = CodeGraphIndexer(Path('$REPO_DIR')).index()
print(f'CodeGraph indexed: {res.files_indexed} files, {res.nodes_count} nodes, {res.edges_count} edges in {res.duration_seconds:.2f}s')
" >> "$LOG_FILE" 2>&1 || log "WARN: Incremental CodeGraph AST indexing failed"
fi

# 3. Vector Database Ingestion if knowledge specs changed
if [ -n "$CHANGED_SPECS" ]; then
  log "Detected knowledge spec changes in commit $(git rev-parse --short HEAD 2>/dev/null):"
  while IFS= read -r spec; do
    log "  - $spec"
  done <<< "$CHANGED_SPECS"

  # Check container/database availability and run ingestion
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^kb-backend$"; then
    log "Running ingestion via active kb-backend container..."
    ./scripts/ingest.sh >> "$LOG_FILE" 2>&1 || log "WARN: ingest.sh failed inside kb-backend"
  elif docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^kb-postgres$"; then
    log "Running ingestion with active kb-postgres container..."
    ./scripts/ingest.sh >> "$LOG_FILE" 2>&1 || log "WARN: ingest.sh failed with active kb-postgres"
  elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^kb-postgres$"; then
    log "Starting stopped kb-postgres container for background vector sync..."
    if docker start kb-postgres >/dev/null 2>&1; then
      # Give PostgreSQL a brief moment to accept connections
      sleep 2
      log "Running ingestion via host environment..."
      ./scripts/ingest.sh >> "$LOG_FILE" 2>&1 || log "WARN: ingest.sh failed"
      log "Restoring kb-postgres to stopped state..."
      docker stop kb-postgres >/dev/null 2>&1 || true
    else
      log "WARN: Failed to start kb-postgres container"
    fi
  else
    log "NOTICE: Docker or kb-postgres not available; skipping automatic background sync."
  fi
fi

log "Auto-ingest lifecycle finished."
