#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -z "$1" ]; then
  echo "Usage: ./scripts/chat.sh \"câu hỏi của bạn\""
  exit 1
fi

if docker ps --format '{{.Names}}' | grep -q "^kb-backend$"; then
  docker exec kb-backend python -m scripts.chat "$@"
else
  cd "$DIR/backend"
  uv run python -m scripts.chat "$@"
fi
