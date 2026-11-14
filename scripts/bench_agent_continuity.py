#!/usr/bin/env python3
"""Benchmark for agent continuity (spec sections 8-9). Stdlib only, Python 3.9.

Phases (results merge into docs/agent-continuity/bench-results.json):
  latency   20 brief runs per mapped repo, backend up, then docker stop kb-backend,
            20 more, always docker start (finally) and wait for /health
  secret    POST a worklog entry holding a fake API key, check the brief hides it
  hook      pipe a SessionStart payload into the real Claude hook command
  inject    N x `agy -p` with a fresh marker in worklog next_steps (injection row)
  continue  N x `agy -p "tiep tuc"` after a fresh handoff marker (scenario 1)
  scenario3 brief --runtime claude must show the latest AGY conversation
  scenario6 unmapped repo: no brief, exit 0

Usage: python3 scripts/bench_agent_continuity.py <phase> [--runs N] [--bench-repo PATH]
Fake values only. Never reads .env.
"""
import argparse
import json
import os
import secrets
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIEF = ROOT / "scripts" / "project_brief.py"
RESULTS = ROOT / "docs" / "agent-continuity" / "bench-results.json"
PROJECTS = ROOT / "config" / "projects.json"
API = os.environ.get("KB_API_URL", "http://localhost:8000")
PY = "/usr/bin/python3"
AGY_DB = Path.home() / ".gemini" / "antigravity-cli" / "conversation_summaries.db"
AGY_BRAIN = Path.home() / ".gemini" / "antigravity-cli" / "brain"
INJECT_PROMPT = ("Không dùng tool nào. Theo PROJECT BRIEF trong ngữ cảnh, bước tiếp theo "
                 "(next_steps) mới nhất là gì? Trả lời một dòng.")
FAKE_SECRET = "sk-test1234567890abcdef"


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_results():
    if RESULTS.exists():
        return json.loads(RESULTS.read_text(encoding="utf-8"))
    return {}


def save(key, value):
    data = load_results()
    data[key] = value
    data["updated_at"] = now()
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_brief(cwd, runtime="agy", stdin_text=""):
    t0 = time.perf_counter()
    p = subprocess.run([PY, str(BRIEF), "--cwd", str(cwd), "--runtime", runtime],
                       input=stdin_text, capture_output=True, text=True, timeout=30)
    return time.perf_counter() - t0, p.returncode, p.stdout, p.stderr


def project_name_for(repo):
    """Name of the mapped project whose repo is `repo` (from config/projects.json)."""
    target = Path(repo).expanduser().resolve()
    for name, cfg in json.loads(PROJECTS.read_text(encoding="utf-8")).items():
        if Path(cfg["repo"]).expanduser().resolve() == target:
            return name
    raise SystemExit("repo %s is not mapped in config/projects.json (map it temporarily, "
                     "then docker restart kb-backend)" % target)


def post_worklog(project, summary, next_steps, kind="handoff", agent="claude"):
    body = json.dumps({"project": project, "kind": kind, "summary": summary,
                       "next_steps": next_steps, "agent": agent}).encode()
    req = urllib.request.Request(API + "/api/v1/agent/worklog", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def health():
    try:
        with urllib.request.urlopen(API + "/health", timeout=2) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


def wait_health(timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        if health():
            return True
        time.sleep(1)
    return False


def pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1) + 0.4999)))] if q < 1 else s[-1]


def stats(samples):
    lat = [s["seconds"] for s in samples]
    return {"n": len(lat), "p50": round(statistics.median(lat), 3), "p95": round(pct(lat, 0.95), 3),
            "max": round(max(lat), 3), "exit_codes": sorted({s["exit"] for s in samples}),
            "chars_max": max(s["chars"] for s in samples),
            "chars_min": min(s["chars"] for s in samples),
            "has_worklog_down_line": sum(1 for s in samples if s["worklog_down"])}


def measure(repos, n):
    out = {}
    for name, repo in repos.items():
        samples = []
        for _ in range(n):
            sec, code, so, _se = run_brief(repo)
            samples.append({"seconds": round(sec, 3), "exit": code, "chars": len(so),
                            "worklog_down": "worklog: không truy cập được" in so})
        out[name] = {"repo": str(repo), "stats": stats(samples), "samples": samples}
    return out


def mapped_repos(include_bench=False):
    raw = json.loads(PROJECTS.read_text(encoding="utf-8"))
    return {k: Path(v["repo"]).expanduser() for k, v in raw.items()
            if include_bench or k != "Continuity-Bench"}


def phase_latency(args):
    repos = mapped_repos(include_bench=False)
    result = {"started_at": now(), "repos": list(repos), "runs_per_repo": args.runs}
    result["backend_up"] = measure(repos, args.runs)
    down = None
    try:
        subprocess.run(["docker", "stop", "kb-backend"], check=True, capture_output=True)
        result["backend_stopped"] = not health()
        down = measure(repos, args.runs)
    finally:
        subprocess.run(["docker", "start", "kb-backend"], capture_output=True)
        result["backend_restarted_healthy"] = wait_health()
    result["backend_down"] = down
    result["finished_at"] = now()
    save("latency", result)
    for mode in ("backend_up", "backend_down"):
        for name, r in (result[mode] or {}).items():
            print(mode, name, r["stats"])
    return 0 if result["backend_restarted_healthy"] else 1


def phase_secret(args):
    # never write fake secrets into a real project's worklog: only the bench project is allowed
    try:
        project = project_name_for(args.bench_repo)
    except SystemExit:
        print("secret: skipped, %s is not mapped (map Continuity-Bench temporarily in "
              "config/projects.json, restart kb-backend, rerun)" % args.bench_repo)
        return 0
    if project != "Continuity-Bench":
        print("secret: skipped, refusing to write a fake secret into real project %s" % project)
        return 0
    line = "OPENAI_API_KEY=" + FAKE_SECRET
    post_worklog(project, "[bench] secret check " + line, "dùng " + line, kind="gotcha")
    _s, code, out, _e = run_brief(args.bench_repo)
    leaked = FAKE_SECRET in out
    res = {"at": now(), "worklog_entry_contains_fake_key": True, "exit": code,
           "brief_contains_secret_value": leaked,
           "redaction_marker_present": "REDACTED" in out.upper() or "***" in out,
           "excerpt": [l for l in out.splitlines() if "tiếp:" in l or "secret check" in l][:3]}
    save("secret", res)
    print(res)
    return 1 if leaked else 0


def phase_hook(args):
    cmd = None
    settings = json.loads((Path.home() / ".claude" / "settings.json").read_text())
    for g in settings["hooks"]["SessionStart"]:
        for h in g["hooks"]:
            if "project_brief.py" in h["command"]:
                cmd = h["command"]
    if cmd is None:
        raise SystemExit("no SessionStart hook running project_brief.py in ~/.claude/settings.json")
    payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup",
                          "session_id": "bench-" + secrets.token_hex(3),
                          "cwd": str(args.bench_repo)})
    results = []
    for source in ("startup", "compact"):
        p = json.loads(payload)
        p["source"] = source
        t0 = time.perf_counter()
        r = subprocess.run(cmd, shell=True, input=json.dumps(p), capture_output=True, text=True,
                           timeout=15, cwd=str(args.bench_repo))
        sec = time.perf_counter() - t0
        try:
            j = json.loads(r.stdout)
            ctx = j["hookSpecificOutput"]["additionalContext"]
            ok = ctx.startswith("PROJECT BRIEF") and j["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        except Exception as exc:  # noqa: BLE001
            ctx, ok = "parse error: %s" % exc, False
        results.append({"source": source, "exit": r.returncode, "seconds": round(sec, 3),
                        "valid_json_with_brief": ok, "header": ctx.splitlines()[0] if ctx else ""})
    save("hook_command_check", {"at": now(), "command": cmd, "runs": results})
    print(results)
    return 0 if all(r["valid_json_with_brief"] and r["exit"] == 0 for r in results) else 1


def agy(prompt, repo, timeout_s):
    t0 = time.perf_counter()
    p = subprocess.run([os.path.expanduser("~/.local/bin/agy"), "-p", prompt, "--print-timeout", "%ds" % timeout_s],
                       cwd=str(repo), capture_output=True, text=True, timeout=timeout_s + 60)
    return {"exit": p.returncode, "seconds": round(time.perf_counter() - t0, 1),
            "stdout": p.stdout[-1500:], "stderr": p.stderr[-300:]}


def newest_conversation(repo):
    import shutil
    import tempfile
    uri = "file://" + str(repo)
    try:
        with tempfile.TemporaryDirectory() as td:
            for suffix in ("", "-wal", "-shm"):
                src = Path(str(AGY_DB) + suffix)
                if src.exists():
                    shutil.copy(src, Path(td) / ("c.db" + suffix))
            con = sqlite3.connect(str(Path(td) / "c.db"))
            row = con.execute("select conversation_id from conversation_summaries where nesting_depth=0 "
                              "and workspace_uris like ? order by last_modified_time desc limit 1",
                              ("%" + uri + "%",)).fetchone()
            con.close()
        return row[0] if row else None
    except Exception:  # noqa: BLE001
        return None


def transcript_has(cid, marker):
    base = AGY_BRAIN / cid / ".system_generated" / "logs"
    for name in ("transcript.jsonl", "transcript_full.jsonl"):
        f = base / name
        if f.exists() and marker in f.read_text(encoding="utf-8", errors="replace"):
            return name
    return None


def transcript_evidence(cid, marker):
    """Which mechanism put the marker in front of the model: injected brief and/or get_worklog."""
    f = AGY_BRAIN / cid / ".system_generated" / "logs" / "transcript.jsonl"
    ev = {"injected_brief_with_marker": False, "get_worklog_result_with_marker": False}
    if not f.exists():
        return ev
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        c = str(j.get("content", ""))
        if marker not in c:
            continue
        if j.get("source") == "SYSTEM_SDK" and c.lstrip().startswith("<USER_REQUEST>\nPROJECT BRIEF"):
            ev["injected_brief_with_marker"] = True
        elif j.get("source") == "MODEL" and j.get("type") == "GENERIC" and "[claude/handoff]" in c:
            ev["get_worklog_result_with_marker"] = True
    return ev


def phase_reanalyze(args):
    data = load_results()
    for key in ("agy_inject", "agy_continue"):
        for r in data.get(key, {}).get("runs", []):
            if r.get("conversation"):
                r["evidence"] = transcript_evidence(r["conversation"], r["marker"])
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def phase_agy(args, mode):
    rows = []
    for i in range(args.runs):
        marker = "AC-" + secrets.token_hex(3)
        post_worklog(project_name_for(args.bench_repo), "bench %s run %d" % (mode, i + 1), "kiểm tra marker " + marker)
        if mode == "inject":
            r = agy(INJECT_PROMPT, args.bench_repo, 150)
        else:
            r = agy("tiếp tục", args.bench_repo, 180)
        cid = newest_conversation(args.bench_repo)
        reply_ok = marker in r["stdout"]
        tr = transcript_has(cid, marker) if cid else None
        passed = reply_ok if mode == "inject" else (reply_ok or tr is not None)
        rows.append({"run": i + 1, "marker": marker, "conversation": cid, "reply_has_marker": reply_ok,
                     "transcript_has_marker": tr, "pass": passed,
                     "evidence": transcript_evidence(cid, marker) if cid else {}, **r})
        print(mode, i + 1, marker, "PASS" if passed else "FAIL", flush=True)
    save("agy_" + mode, {"at": now(), "prompt": INJECT_PROMPT if mode == "inject" else "tiếp tục",
                         "passed": sum(1 for r in rows if r["pass"]), "total": len(rows), "runs": rows})
    return 0


def phase_scenario3(args):
    _s, code, out, _e = run_brief(args.bench_repo, runtime="claude")
    block = out[out.find("Phiên trước"):] if "Phiên trước" in out else ""
    save("scenario3_claude_side", {"at": now(), "exit": code, "has_phien_truoc_agy": "Phiên trước (agy" in out,
                                   "excerpt": block[:900]})
    print(block[:900])
    return 0 if "Phiên trước (agy" in out else 1


def phase_sizes(args):
    """Brief size/time for a repo with a real worklog and real sessions (default: personal-kb)."""
    res = {"at": now(), "repo": str(args.bench_repo), "runs": {}}
    for rt in ("agy", "claude"):
        sec, code, out, _e = run_brief(args.bench_repo, runtime=rt)
        res["runs"][rt] = {"seconds": round(sec, 3), "exit": code, "chars": len(out),
                           "has_previous_session": "Phiên trước" in out,
                           "worklog_entries": sum(1 for l in out.splitlines() if l.startswith("- 20"))}
    save("sizes_real_worklog", res)
    print(res)
    return 0


def phase_scenario6(args):
    repo = Path.home() / "Project" / "MyEQ"
    sec, code, out, err = run_brief(repo)
    save("scenario6_unmapped", {"at": now(), "repo": str(repo), "exit": code, "stdout_chars": len(out),
                                "stdout_empty": out.strip() == "", "stderr_chars": len(err)})
    print(code, repr(out[:80]))
    return 0 if code == 0 and out.strip() == "" else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["latency", "secret", "hook", "inject", "continue",
                                      "scenario3", "scenario6", "reanalyze", "sizes"])
    ap.add_argument("--runs", type=int, default=None)
    ap.add_argument("--bench-repo", type=Path, default=None,
                    help="default: ~/Project/personal-kb for hook/sizes, ~/Project/_continuity-bench "
                         "(needs a temporary mapping) for secret/inject/continue/scenario3")
    a = ap.parse_args()
    if a.bench_repo is None:
        own = a.phase in ("hook", "sizes")
        a.bench_repo = Path.home() / "Project" / ("personal-kb" if own else "_continuity-bench")
    if a.runs is None:
        a.runs = {"latency": 20, "inject": 10, "continue": 3}.get(a.phase, 1)
    fn = {"latency": phase_latency, "secret": phase_secret, "hook": phase_hook,
          "inject": lambda x: phase_agy(x, "inject"), "continue": lambda x: phase_agy(x, "continue"),
          "scenario3": phase_scenario3, "scenario6": phase_scenario6,
          "reanalyze": phase_reanalyze, "sizes": phase_sizes}[a.phase]
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
