#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

echo "Running Personal-KB Agent Setup..."
if command -v uv >/dev/null 2>&1; then
  uv run python scripts/setup_agent.py "$@"
elif command -v python3 >/dev/null 2>&1; then
  python3 scripts/setup_agent.py "$@"
else
  echo "Error: Python 3 or uv is required."
  exit 1
fi
