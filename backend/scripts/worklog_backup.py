"""Back up and restore the worklog, the one table not rebuilt from knowledge/ (scripts/backup_worklog.sh).

Usage, inside kb-backend:
  python -m scripts.worklog_backup export > worklog.jsonl     every entry, oldest first, one JSON object per line
  python -m scripts.worklog_backup restore < worklog.jsonl    adds the entries whose id is missing; prints how many
"""

import asyncio
import dataclasses
import json
import logging
import sys
from datetime import datetime

from personal_kb.core.config import get_settings
from personal_kb.infrastructure.memory_backend import build_memory
from personal_kb.infrastructure.postgres.pg_worklog_store import WorklogRestoreConflict
from personal_kb.services.redaction import redact
from personal_kb.services.worklog import WorklogEntry

# entries written before redaction on write existed may still hold a secret: the backup goes to git
_TEXT = ("summary", "next_steps", "agent", "session_id", "branch")


def to_line(entry: WorklogEntry) -> str:
    fields = dataclasses.asdict(entry) | {"created_at": entry.created_at.isoformat()}
    fields |= {name: redact(fields[name]) for name in _TEXT}
    return json.dumps(fields, ensure_ascii=False)


def from_line(line: str) -> WorklogEntry:
    fields = json.loads(line)
    return WorklogEntry(**fields | {"created_at": datetime.fromisoformat(fields["created_at"])})


async def main(command: str) -> None:
    async with build_memory(get_settings()) as stores:
        if command == "export":
            for entry in await stores.worklog.all_entries():
                print(to_line(entry))
        elif command == "restore":
            entries = [from_line(line) for line in sys.stdin if line.strip()]
            try:
                added = await stores.worklog.restore(entries)
            except WorklogRestoreConflict as exc:
                raise SystemExit(f"restore refused, nothing written: {exc}") from None
            print(f"restored {added} of {len(entries)} entries", file=sys.stderr)
        else:
            raise SystemExit("usage: python -m scripts.worklog_backup export|restore")


if __name__ == "__main__":
    logging.disable(logging.WARNING)  # stdout carries the backup
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else ""))
