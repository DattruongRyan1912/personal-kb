#!/bin/bash
# The full backend suite against the local kb-postgres: POSTGRES_URL is read from kb-backend (host rewritten to the
# published port) into a private temp file, never printed. Extra arguments go to pytest.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! docker ps --format '{{.Names}}' | grep -q "^kb-backend$"; then
  echo "kb-backend is not running: docker compose up -d" >&2
  exit 1
fi

umask 077
envfile="${TMPDIR:-/tmp}/personal-kb-test.env"
url="$(docker exec kb-backend printenv POSTGRES_URL | sed -E 's#@[^/]+/#@127.0.0.1:5434/#')"
printf 'POSTGRES_URL=%s\nPOSTGRES_REQUIRED=1\n' "$url" > "$envfile"

cd "$DIR/backend"
exec uv run --env-file ../.env --env-file "$envfile" pytest -q "$@"
