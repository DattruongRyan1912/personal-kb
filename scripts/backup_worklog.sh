#!/bin/bash
# Back up the worklog (agent progress) to docs/worklog/worklog.jsonl: the one table not rebuilt from knowledge/.
# Commit the file to keep it. Restore: docker exec -i kb-backend python -m scripts.worklog_backup restore < <file>
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$DIR/docs/worklog/worklog.jsonl"
mkdir -p "$(dirname "$OUT")"

docker exec kb-backend python -m scripts.worklog_backup export > "$OUT.tmp"
# fewer entries than the last backup means a reset database: keep the backup (FORCE=1 to replace it anyway)
if [ -f "$OUT" ] && [ "$(wc -l < "$OUT.tmp")" -lt "$(wc -l < "$OUT")" ] && [ "${FORCE:-0}" != "1" ]; then
  rm -f "$OUT.tmp"
  echo "refused: the database has fewer worklog entries than ${OUT#"$DIR/"}; restore it first, or FORCE=1" >&2
  exit 1
fi
mv "$OUT.tmp" "$OUT"
echo "worklog: $(wc -l < "$OUT" | tr -d ' ') entries -> ${OUT#"$DIR/"}"
