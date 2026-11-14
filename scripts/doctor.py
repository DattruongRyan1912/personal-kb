#!/usr/bin/env python3
"""Checks the stack and the agents' MCP config for the drifts that fail silently (stdlib only, /usr/bin/python3).

- the backend is up and its config/ bind mount is not stale (an empty /app/config rejects every worklog write);
- Claude desktop and Claude Code run this repo's MCP server (the app has rewritten its config to another one), and it
  can run on the host (without backend/.venv it falls back to docker exec, and sessions lose it on a backend restart);
- every spec in knowledge/ is in the store;
- the re-ranker answers (WARN only: without it search runs unranked).

Prints `OK|WARN|FAIL <check>: <verdict>`, never a config value; exits 1 when a check fails.
Usage: /usr/bin/python3 scripts/doctor.py [--json]
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP_CONFIG = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
CODE_CONFIG = Path.home() / ".claude.json"
BACKEND = "http://127.0.0.1:8000"
RERANKER = "http://127.0.0.1:8081"
MCP_PYTHON = REPO / "backend" / ".venv" / "bin" / "python"


def check_mcp_entry(config, repo):
    server = (config.get("mcpServers") or {}).get("personal-kb")
    if not server:
        return False, "no personal-kb server"
    args = [str(a) for a in server.get("args") or []]
    repo_str = str(repo)
    if args and args[-1] == str(repo / "scripts" / "mcp_server.sh"):
        return True, "runs scripts/mcp_server.sh"
    if "personal_kb.mcp.cli" in args and any(repo_str in a for a in args):
        return True, "runs personal_kb.mcp.cli from this repo via uv"
    paths = [a for a in [str(server.get("command", "")), *args] if a.startswith("/")]
    return False, f"runs another server: {', '.join(paths) or 'no path'}"


def check_project_map(target):
    if hasattr(target, "returncode"):
        if target.returncode != 0:
            err = (target.stderr or target.stdout).strip().splitlines()
            msg = err[0] if err else f"exit {target.returncode}"
            return False, f"kb-backend unreachable or offline ({msg})"
        listing = target.stdout.split()
    elif isinstance(target, (list, set, tuple)):
        listing = target
    else:
        listing = []

    if "projects.json" in listing:
        return True, "/app/config/projects.json mounted"
    return False, "/app/config is empty (stale bind mount): docker compose up -d --force-recreate backend"


def check_documents(stored, on_disk):
    if hasattr(stored, "returncode"):
        if stored.returncode != 0:
            err = (stored.stderr or stored.stdout).strip().splitlines()
            msg = err[0] if err else f"exit {stored.returncode}"
            return False, f"kb-postgres unreachable or offline ({msg})"
        stored = set(filter(None, (line.strip() for line in stored.stdout.splitlines())))

    if isinstance(stored, (set, list, tuple)) and isinstance(on_disk, (set, list, tuple)):
        stored_set = set(stored)
        disk_set = set(on_disk)
        if stored_set == disk_set:
            return True, f"{len(stored_set)} documents synchronized (IDs matched 1:1)"
        missing_in_db = disk_set - stored_set
        orphan_in_db = stored_set - disk_set
        reasons = []
        if missing_in_db:
            sample = sorted(missing_in_db)[:3]
            reasons.append(f"{len(stored_set)} documents but {len(disk_set)} specs on disk (missing {sample}): ./scripts/ingest.sh")
        if orphan_in_db:
            sample = sorted(orphan_in_db)[:3]
            reasons.append(f"{len(orphan_in_db)} not on disk any more (orphaned {sample}): delete them in the Data Hub")
        return False, "; ".join(reasons)

    # Integer comparison fallback for backwards compatibility
    if stored == on_disk:
        return True, f"{stored} documents, {on_disk} specs on disk"
    if stored < on_disk:
        return False, f"{stored} documents but {on_disk} specs on disk: ./scripts/ingest.sh"
    return False, f"{stored} documents, {stored - on_disk} not on disk any more: delete them in the Data Hub"


def reranker_level(scores):
    if isinstance(scores, list) and scores:
        return "OK", "answers on :8081"
    return "WARN", "not reachable on :8081: search results are unranked"


def mcp_runtime_level(python):
    if python.is_file() and os.access(python, os.X_OK):
        return "OK", "runs on the host from backend/.venv"
    return "WARN", "no backend/.venv: runs via docker exec and drops on a kb-backend restart (cd backend && uv sync)"


def render(results, as_json):
    if as_json:
        return json.dumps([{"level": level, "check": name, "verdict": verdict} for level, name, verdict in results])
    return "\n".join(f"{level:<4} {name}: {verdict}" for level, name, verdict in results)


def exit_code(results):
    return 1 if any(level == "FAIL" for level, _, _ in results) else 0


def _run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=20)


def _http(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _specs_on_disk_ids():
    import re

    ids = set()
    for p in (REPO / "knowledge").rglob("*.md"):
        if "proposals" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8")
            m = re.search(r"^id:\s*([^\n\r]+)", text, re.MULTILINE)
            ids.add(m.group(1).strip().strip("\"'") if m else p.stem)
        except OSError:
            ids.add(p.stem)
    return ids


def _specs_on_disk():
    return len(_specs_on_disk_ids())


def main():
    results = []

    def add(name, check):
        try:
            ok, verdict = check()
            results.append(("OK" if ok else "FAIL", name, verdict))
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the others
            results.append(("FAIL", name, type(exc).__name__))

    add("backend", lambda: (_http(BACKEND + "/health").get("status") == "ok", BACKEND + "/health"))
    add("config mount", lambda: check_project_map(_run("docker", "exec", "kb-backend", "ls", "/app/config")))
    add("claude desktop mcp", lambda: check_mcp_entry(_read_json(DESKTOP_CONFIG), REPO))
    add("claude code mcp", lambda: check_mcp_entry(_read_json(CODE_CONFIG), REPO))
    level, verdict = mcp_runtime_level(MCP_PYTHON)
    results.append((level, "mcp runtime", verdict))
    id_sql = "select spec_id from documents order by spec_id"
    add("documents", lambda: check_documents(
        _run("docker", "exec", "kb-postgres", "sh", "-c",
             f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "{id_sql}"'),
        _specs_on_disk_ids(),
    ))
    try:
        scores = _http(RERANKER + "/rerank", {"query": "a", "texts": ["a"]})
    except Exception:  # noqa: BLE001
        scores = None
    level, verdict = reranker_level(scores)
    results.append((level, "reranker", verdict))

    print(render(results, as_json="--json" in sys.argv[1:]))  # noqa: T201 - the report is the output
    raise SystemExit(exit_code(results))


if __name__ == "__main__":
    main()
