import ast
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/project_brief.py"
_spec = importlib.util.spec_from_file_location("project_brief", SCRIPT)
pb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pb)

AUTHOR = "dattruong19122003@gmail.com"
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo, *args, email=AUTHOR):
    env = {**os.environ, **GIT_ENV}
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", f"user.email={email}", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=env,
    )


def _project(repo):
    return pb.Project(name="P", repo=Path(repo).resolve(), git_author=AUTHOR)


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "mine one")
    (repo / "b.txt").write_text("b")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "theirs two", email="other@example.com")
    (repo / "c.txt").write_text("c")  # untracked / dirty
    (repo / "a.txt").write_text("changed")
    return repo


def test_resolve_project_subdirectory_and_symlink(tmp_path):
    repo = tmp_path / "repo"
    (repo / "sub/deep").mkdir(parents=True)
    (tmp_path / "repo2").mkdir()
    link = tmp_path / "link"
    link.symlink_to(repo)
    cfg = tmp_path / "projects.json"
    cfg.write_text(
        json.dumps(
            {
                "Outer": {"repo": str(tmp_path), "git_author": "x"},
                "P": {"repo": str(repo), "git_author": "x"},
            }
        )
    )
    projects = pb.load_projects(cfg)
    assert pb.resolve_project(repo, projects).name == "P"
    assert pb.resolve_project(repo / "sub/deep", projects).name == "P"
    assert pb.resolve_project(link / "sub", projects).name == "P"
    # sibling repo2 must not match P (string prefix trap); falls to Outer
    assert pb.resolve_project(tmp_path / "repo2", projects).name == "Outer"
    only_p = {"P": projects["P"]}
    assert pb.resolve_project(tmp_path / "repo2", only_p) is None


def test_resolve_project_unmapped_is_none(tmp_path):
    (tmp_path / "x").mkdir()
    p = pb.Project("P", (tmp_path / "other").resolve(), "a")
    assert pb.resolve_project(tmp_path / "x", {"P": p}) is None


def test_git_section_lists_branch_dirty_files_and_only_author_commits(git_repo):
    out = pb.git_section(_project(git_repo), now=datetime.now(UTC))
    assert "main" in out
    assert "mine one" in out
    assert "theirs two" not in out
    assert "a.txt" in out and "c.txt" in out
    assert len([line for line in out.splitlines() if line.strip()]) <= 1 + 1 + 8 + 1 + 10 + 2


def test_git_section_caps_commits_and_files(git_repo):
    for i in range(12):
        (git_repo / f"f{i}.txt").write_text(str(i))
        _git(git_repo, "add", f"f{i}.txt")
        _git(git_repo, "commit", "-q", "-m", f"mine c{i}")
    for i in range(15):
        (git_repo / f"d{i}.txt").write_text("x")
    out = pb.git_section(_project(git_repo), now=datetime.now(UTC))
    assert sum(1 for line in out.splitlines() if "mine c" in line or "mine one" in line) <= 8
    assert sum(1 for line in out.splitlines() if line.strip().endswith(".txt")) <= 10


def test_git_section_not_a_repo_is_empty(tmp_path):
    assert pb.git_section(_project(tmp_path), now=datetime.now(UTC)) == ""


def test_git_section_git_missing_is_empty(git_repo, monkeypatch):
    monkeypatch.setenv("PATH", str(git_repo))
    assert pb.git_section(_project(git_repo), now=datetime.now(UTC)) == ""


class _Server:
    def __init__(self, handler):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


ENTRIES = [
    {
        "id": 2,
        "project": "P",
        "kind": "progress",
        "summary": "Added brief script",
        "next_steps": "wire main()",
        "agent": "claude",
        "session_id": "s1",
        "branch": "feat/x",
        "created_at": "2026-10-24T10:00:00+00:00",
    },
    {
        "id": 1,
        "project": "P",
        "kind": "decision",
        "summary": "Chose stdlib only",
        "next_steps": None,
        "agent": "agy",
        "session_id": "s0",
        "branch": None,
        "created_at": "2026-10-23T09:00:00Z",
    },
]


def test_worklog_section_formats_entries(tmp_path):
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["path"] = self.path
            body = json.dumps(ENTRIES).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = _Server(H)
    try:
        out = pb.worklog_section(_project(tmp_path), base_url=srv.url)
    finally:
        srv.close()
    assert "Added brief script" in out and "Chose stdlib only" in out
    assert "wire main()" in out
    assert "project=P" in seen["path"] and "limit=5" in seen["path"]


def test_worklog_section_down_or_slow_degrades(tmp_path):
    degraded = "worklog: không truy cập được"
    s = _Server(BaseHTTPRequestHandler)
    url = s.url
    s.close()  # closed port
    assert pb.worklog_section(_project(tmp_path), base_url=url) == degraded

    class Slow(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(3)

        def log_message(self, *a):
            pass

    srv = _Server(Slow)
    try:
        t = time.monotonic()
        out = pb.worklog_section(_project(tmp_path), base_url=srv.url)
        assert time.monotonic() - t < 2.5
    finally:
        srv.close()
    assert out == degraded


def test_worklog_section_bad_json_degrades(tmp_path):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "3")
            self.end_headers()
            self.wfile.write(b"zzz")

        def log_message(self, *a):
            pass

    srv = _Server(H)
    try:
        assert pb.worklog_section(_project(tmp_path), base_url=srv.url) == "worklog: không truy cập được"
    finally:
        srv.close()


def test_redact_masks_secrets():
    secrets = [
        "sk-abcdefghijklmnopqrstuvwxyz123456",
        "sk-proj-AbCdEf_1234567890-abcdefghij",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "github_pat_11ABCDEFG0abcdefghijkl_mnopqrstuvwxyz0123456789",
        "AIzaSyA-1234567890abcdefghijklmnopqrstuv",
        "AQ." + "Ab8RN6Jabcdefghijklmnop_qrstuvwxyz-0123456789",
        "hunter2secret",
    ]
    for s in secrets[:-1]:
        assert pb.redact(f"key {s} end") == "key [REDACTED] end", s
    assert pb.redact("Authorization: Bearer abc.def-123_xyz=") == "Authorization: Bearer [REDACTED]"
    for name in ("password", "token", "api_key", "secret"):
        out = pb.redact(f"{name}=hunter2secret rest")
        assert "hunter2secret" not in out and "[REDACTED]" in out and "rest" in out
    assert pb.redact('PASSWORD: "hunter2secret"').count("hunter2secret") == 0
    assert pb.redact("plain text, task-1 and ask.me") == "plain text, task-1 and ask.me"


@pytest.mark.parametrize(
    "text",
    [
        "DB_PASSWORD=hunter2x",
        "export GITHUB_TOKEN=abc123",
        "OPENAI_API_KEY=zzz",
        "access_token=abc123",
        "client_secret=abc123",
        '{"password": "hunter2x"}',
        "{'api_key': 'hunter2x'}",
    ],
)
def test_redact_env_style_and_json(text):
    out = pb.redact(text)
    assert "[REDACTED]" in out
    for leaked in ("hunter2x", "abc123", "zzz"):
        assert leaked not in out


def test_git_section_redacts_before_truncating(git_repo):
    secret = "sk-" + "A" * 40
    (git_repo / "d.txt").write_text("d")
    _git(git_repo, "add", "d.txt")
    _git(git_repo, "commit", "-q", "-m", "x" * 85 + " " + secret)
    out = pb.git_section(_project(git_repo), now=datetime.now(UTC))
    assert "sk-" not in out


def test_sections_are_redacted(tmp_path):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            e = dict(ENTRIES[0], summary="used sk-abcdefghijklmnopqrstuvwxyz123456")
            body = json.dumps([e]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = _Server(H)
    try:
        out = pb.worklog_section(_project(tmp_path), base_url=srv.url)
    finally:
        srv.close()
    assert "sk-abcdef" not in out and "[REDACTED]" in out


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="no system python")
def test_module_imports_under_system_python():
    code = (
        "import importlib.util,sys; "
        f"s=importlib.util.spec_from_file_location('pb', {str(SCRIPT)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)"
    )
    r = subprocess.run(["/usr/bin/python3", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- Task 7 ----


_CWD = ["/x"]  # cwd recorded in fake Claude transcripts (set by repo_dir)


def _claude_line(
    kind, content, *, sid="s", meta=None, sidechain=False, ts="2026-10-24T10:00:00.000Z", cwd=None, **extra
):
    d = {
        "type": kind,
        "isSidechain": sidechain,
        "sessionId": sid,
        "cwd": cwd or _CWD[0],
        **extra,
        "timestamp": ts,
        "message": {"role": kind, "content": content},
    }
    if meta is not None:
        d["isMeta"] = meta
    return json.dumps(d)


def _write_session(root, slug, sid, lines, mtime=None, sub=None):
    d = Path(root) / slug
    if sub:
        d = d / sub
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if mtime:
        os.utime(f, (mtime, mtime))
    return f


def _slug(p):
    # Claude Code turns every non-alphanumeric (/, ., _ ...) into "-"
    return "".join(c if c.isalnum() or c == "-" else "-" for c in str(p))


@pytest.fixture
def repo_dir(tmp_path):
    r = tmp_path / "work" / "my.repo"
    r.mkdir(parents=True)
    _CWD[0] = str(r.resolve())
    return r.resolve()


def test_claude_last_session_skips_meta_sidechain_tool_results_and_subagents(tmp_path, repo_dir):
    root = tmp_path / "claude"
    slug = _slug(repo_dir)
    lines = [
        _claude_line("user", "first question"),
        _claude_line("assistant", [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "real answer"}]),
        _claude_line("user", "meta caveat", meta=True),
        _claude_line("user", "sidechain ask", sidechain=True),
        _claude_line("user", [{"type": "tool_result", "content": "tool output"}]),
        _claude_line("user", [{"type": "text", "text": "last real "}, {"type": "text", "text": "ask"}]),
        _claude_line("user", "<task-notification> <task-id>x</task-id> </task-notification>"),
        _claude_line("attachment", "ignored"),
        _claude_line("assistant", [{"type": "tool_use", "name": "Bash"}]),
        "{not json",
    ]
    _write_session(root, slug, "main1", lines, mtime=1_000_000)
    # newer subagent transcript must be ignored
    _write_session(
        root,
        slug,
        "sub1",
        [_claude_line("user", "SUBAGENT"), _claude_line("assistant", [{"type": "text", "text": "SUBAGENT"}])],
        mtime=2_000_000,
        sub="main1/subagents",
    )
    s = pb.claude_last_session(repo_dir, root=root)
    assert s.runtime == "claude" and s.session_id == "main1"
    assert s.last_user == "last real ask"
    assert s.last_reply == "real answer"
    assert s.at.tzinfo is not None


def test_claude_last_session_includes_subdirectory_slug_and_excludes_current(tmp_path, repo_dir):
    root = tmp_path / "claude"
    slug = _slug(repo_dir)
    ok = [_claude_line("user", "u"), _claude_line("assistant", [{"type": "text", "text": "a"}])]
    _write_session(root, slug, "top", ok, mtime=1_000_000)
    _write_session(root, slug + "-scripts", "subdir", ok, mtime=2_000_000)
    _write_session(root, slug + "2", "sibling", ok, mtime=3_000_000)  # other repo, prefix trap
    _write_session(root, "-other", "other", ok, mtime=4_000_000)
    assert pb.claude_last_session(repo_dir, root=root).session_id == "subdir"
    assert pb.claude_last_session(repo_dir, root=root, exclude="subdir").session_id == "top"
    assert pb.claude_last_session(repo_dir, root=tmp_path / "nope") is None


def _agy_db(root, rows):
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "conversation_summaries.db")
    con.execute(
        "CREATE TABLE conversation_summaries (conversation_id TEXT, title TEXT, step_count INT,"
        " last_modified_time TEXT, workspace_uris TEXT, nesting_depth INT,"
        " parent_conversation_id TEXT, agent_name TEXT)"
    )
    for r in rows:
        con.execute(
            "INSERT INTO conversation_summaries VALUES (?,?,?,?,?,?,?,?)",
            (
                r["id"],
                "t",
                1,
                r["t"],
                json.dumps(["file://" + w for w in r["ws"]]),
                r.get("depth", 0),
                r.get("parent", ""),
                r.get("agent", ""),
            ),
        )
    con.commit()
    con.close()


def _agy_transcript(root, cid, lines):
    d = root / "brain" / cid / ".system_generated" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "transcript.jsonl").write_text(
        "\n".join(json.dumps(x) if isinstance(x, dict) else x for x in lines) + "\n", encoding="utf-8"
    )


def _agy_turns(user, reply):
    return [
        {
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "created_at": "x",
            "content": f"<USER_REQUEST>\n{user}\n</USER_REQUEST>",
        },
        {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": reply, "thinking": "secret thoughts"},
        {"source": "SYSTEM", "type": "SYSTEM_MESSAGE", "content": "sys"},
    ]


def test_agy_last_session_picks_main_conversation_in_repo(tmp_path, repo_dir):
    root = tmp_path / "agy"
    other = tmp_path / "work" / "other"
    _agy_db(
        root,
        [
            {
                "id": "nested",
                "t": "2026-10-24 12:30:00.000000+00:00",
                "ws": [str(repo_dir)],
                "depth": 1,
                "parent": "main",
            },
            {"id": "elsewhere", "t": "2026-10-24 12:25:00.000000+00:00", "ws": [str(other)]},
            {"id": "sibling", "t": "2026-10-24 12:24:00.000000+00:00", "ws": [str(repo_dir) + "2"]},
            {"id": "inrepo", "t": "2026-10-24 12:00:00.000000+00:00", "ws": [str(repo_dir / "sub")]},
            {"id": "older", "t": "2026-10-23 12:00:00.000000+00:00", "ws": [str(repo_dir)]},
        ],
    )
    _agy_transcript(root, "inrepo", _agy_turns("do the thing", "done the thing"))
    _agy_transcript(root, "older", _agy_turns("old", "old reply"))
    s = pb.agy_last_session(repo_dir, root=root)
    assert s.runtime == "agy" and s.session_id == "inrepo"
    assert s.last_user == "do the thing" and s.last_reply == "done the thing"
    assert s.at == datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    assert pb.agy_last_session(repo_dir, root=root, exclude="inrepo").session_id == "older"
    assert pb.agy_last_session(repo_dir, root=tmp_path / "none") is None


def test_agy_last_session_reads_wal_db_without_shm(tmp_path, repo_dir):
    root = tmp_path / "agy"
    _agy_db(root, [{"id": "w", "t": "2026-10-24 12:00:00.000000+00:00", "ws": [str(repo_dir)]}])
    con = sqlite3.connect(root / "conversation_summaries.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.commit()
    con.close()
    for suffix in ("-wal", "-shm"):
        (root / ("conversation_summaries.db" + suffix)).unlink(missing_ok=True)
    _agy_transcript(root, "w", _agy_turns("q", "a"))
    assert pb.agy_last_session(repo_dir, root=root).session_id == "w"


def test_agy_turns_skip_plugin_injected_user_input(tmp_path):
    f = tmp_path / "t.jsonl"
    lines = _agy_turns("tiếp tục", "done")
    lines.insert(
        1,
        {"source": "SYSTEM_SDK", "type": "USER_INPUT", "content": "<USER_REQUEST>\nPROJECT BRIEF — x\n</USER_REQUEST>"},
    )
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    assert pb._agy_turns(f) == ("tiếp tục", "done")


def test_agy_advisor_conversation_is_ignored(tmp_path, repo_dir):
    root = tmp_path / "agy"
    _agy_db(
        root,
        [
            {"id": "adv", "t": "2026-10-24 13:00:00.000000+00:00", "ws": [str(repo_dir)], "agent": "advisor"},
            {"id": "main", "t": "2026-10-24 12:00:00.000000+00:00", "ws": [str(repo_dir)]},
        ],
    )
    _agy_transcript(root, "adv", _agy_turns("advisor ask", "advisor reply"))
    _agy_transcript(root, "main", _agy_turns("main ask", "main reply"))
    assert pb.agy_last_session(repo_dir, root=root).session_id == "main"


def test_transcript_malformed_partial_and_huge_lines(tmp_path, repo_dir):
    root = tmp_path / "claude"
    slug = _slug(repo_dir)
    huge = "Z" * 1_000_000
    mid = "M" * 300_000 + " tail"
    lines = [
        _claude_line("user", huge),  # beyond the 512 KB tail window
        "this is not json",
        _claude_line("assistant", [{"type": "text", "text": "ok reply"}]),
        _claude_line("user", mid),  # huge but inside the window
        '{"type": "user", "message": {"role": "user", "cont',  # half-written last line
    ]
    f = _write_session(root, slug, "s1", lines)
    f.write_bytes(f.read_bytes().rstrip(b"\n"))
    s = pb.claude_last_session(repo_dir, root=root)
    assert s is not None
    assert len(s.last_user) <= 400 and len(s.last_reply) <= 400
    assert s.last_user.startswith("M")
    brief_text = pb._session_block(s, 400)
    assert len(brief_text) < 1200


def test_large_transcript_tail_read_is_fast(tmp_path, repo_dir):
    root = tmp_path / "claude"
    slug = _slug(repo_dir)
    d = root / slug
    d.mkdir(parents=True)
    filler = _claude_line("assistant", [{"type": "text", "text": "f" * 2000}]).encode() + b"\n"
    with open(d / "big.jsonl", "wb") as fh:
        for _ in range(4000):  # ~8 MB
            fh.write(filler)
        fh.write(_claude_line("user", "the very last ask").encode() + b"\n")
        fh.write(_claude_line("assistant", [{"type": "text", "text": "the very last answer"}]).encode() + b"\n")
    assert (d / "big.jsonl").stat().st_size > 8_000_000
    t = time.monotonic()
    s = pb.claude_last_session(repo_dir, root=root)
    assert time.monotonic() - t < 0.3
    assert s.last_user == "the very last ask" and s.last_reply == "the very last answer"


def _cfg(tmp_path, repo, name="P"):
    cfg = tmp_path / "projects.json"
    cfg.write_text(json.dumps({name: {"repo": str(repo), "git_author": AUTHOR}}))
    return cfg


def _worklog_server(entries):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(entries).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return _Server(H)


@pytest.fixture
def both_roots(tmp_path, repo_dir, monkeypatch):
    claude = tmp_path / "claude"
    agy = tmp_path / "agy"
    _write_session(
        claude,
        _slug(repo_dir),
        "cs1",
        [
            _claude_line("user", "claude ask CLAUDE_MARK"),
            _claude_line("assistant", [{"type": "text", "text": "claude reply"}]),
        ],
    )
    _agy_db(agy, [{"id": "as1", "t": "2026-10-24 12:00:00.000000+00:00", "ws": [str(repo_dir)]}])
    _agy_transcript(agy, "as1", _agy_turns("agy ask AGY_MARK", "agy reply"))
    monkeypatch.setattr(pb, "CLAUDE_ROOT", claude)
    monkeypatch.setattr(pb, "AGY_ROOT", agy)
    return claude, agy


def test_build_brief_other_runtime_only(tmp_path, repo_dir, both_roots):
    srv = _worklog_server(ENTRIES)
    try:
        cfg = _cfg(tmp_path, repo_dir)
        a = pb.build_brief(repo_dir, runtime="agy", projects_path=cfg, base_url=srv.url)
        c = pb.build_brief(repo_dir, runtime="claude", projects_path=cfg, base_url=srv.url)
    finally:
        srv.close()
    assert a.startswith(f"PROJECT BRIEF — P ({repo_dir})")
    assert "CLAUDE_MARK" in a and "AGY_MARK" not in a
    assert "AGY_MARK" in c and "CLAUDE_MARK" not in c
    assert "Phiên trước" in a and "Added brief script" in a and "log_progress" in a
    assert len(a) <= 2500 and len(c) <= 2500


def test_build_brief_unmapped_is_empty(tmp_path, repo_dir):
    cfg = _cfg(tmp_path, tmp_path / "somewhere-else")
    assert pb.build_brief(repo_dir, runtime="agy", projects_path=cfg, base_url="http://127.0.0.1:1") == ""


def test_build_brief_budget_2500(tmp_path, repo_dir, both_roots, monkeypatch):
    claude, _ = both_roots
    big = "W" * 5000
    _write_session(
        claude,
        _slug(repo_dir),
        "cs2",
        [_claude_line("user", big), _claude_line("assistant", [{"type": "text", "text": big}])],
    )
    entries = [dict(ENTRIES[0], id=i, summary=big, next_steps=big) for i in range(5)]
    srv = _worklog_server(entries)
    _git(repo_dir, "init", "-q", "-b", "main")
    for i in range(12):
        (repo_dir / f"f{i}.txt").write_text("x")
        _git(repo_dir, "add", ".")
        _git(repo_dir, "commit", "-q", "-m", "mine " + "y" * 90)
    for i in range(15):
        (repo_dir / f"d{i}.txt").write_text("x")
    try:
        out = pb.build_brief(repo_dir, runtime="agy", projects_path=_cfg(tmp_path, repo_dir), base_url=srv.url)
    finally:
        srv.close()
    assert len(out) <= 2500
    assert out.startswith("PROJECT BRIEF — P")
    assert "Worklog gần đây" in out


def test_worklog_secret_is_redacted_in_brief(tmp_path, repo_dir, both_roots):
    claude, _ = both_roots
    _write_session(
        claude,
        _slug(repo_dir),
        "cs3",
        [
            _claude_line("user", "use sk-abcdefghijklmnopqrstuvwxyz123456 and DB_PASSWORD=hunter2x now"),
            _claude_line(
                "assistant",
                [
                    {
                        "type": "text",
                        "text": 'Bearer abc.def-123 ghp_abcdefghijklmnopqrstuvwxyz0123456789 {"password": "hunter2x"} '
                        "AQ.Ab8RN6Jabcdefghijklmnop_qrstuvwxyz GITHUB_TOKEN=zzz9",
                    }
                ],
            ),
        ],
        mtime=time.time() + 100,
    )
    entries = [
        dict(
            ENTRIES[0],
            summary="leak sk-abcdefghijklmnopqrstuvwxyz123456 password=hunter2x",
            next_steps='{"api_key": "hunter2x"}',
        )
    ]
    srv = _worklog_server(entries)
    try:
        out = pb.build_brief(repo_dir, runtime="agy", projects_path=_cfg(tmp_path, repo_dir), base_url=srv.url)
    finally:
        srv.close()
    assert "[REDACTED]" in out
    for leaked in ("sk-abcdef", "hunter2x", "ghp_abc", "abc.def-123", "AQ.Ab8", "zzz9"):
        assert leaked not in out, leaked


def test_main_claude_hook_format_and_exit_zero_on_error(tmp_path, repo_dir, both_roots, monkeypatch, capsys):
    srv = _worklog_server(ENTRIES)
    monkeypatch.setenv("KB_API_URL", srv.url)
    cfg = _cfg(tmp_path, repo_dir)
    payload = json.dumps({"cwd": str(repo_dir), "session_id": "cs1", "hook_event_name": "SessionStart"})
    try:
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
        rc = pb.main(["--runtime", "claude", "--format", "claude-hook", "--projects", str(cfg)])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "AGY_MARK" in data["hookSpecificOutput"]["additionalContext"]
        # text format
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        rc = pb.main(["--cwd", str(repo_dir), "--runtime", "agy", "--projects", str(cfg)])
        assert rc == 0 and "CLAUDE_MARK" in capsys.readouterr().out
    finally:
        srv.close()
    # error paths
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    rc = pb.main(
        [
            "--cwd",
            str(repo_dir),
            "--runtime",
            "claude",
            "--format",
            "claude-hook",
            "--projects",
            str(tmp_path / "missing.json"),
        ]
    )
    assert rc == 0 and capsys.readouterr().out.strip() == "{}"
    rc = pb.main(["--cwd", str(repo_dir), "--projects", str(tmp_path / "missing.json")])
    assert rc == 0 and capsys.readouterr().out == ""
    # unmapped cwd in hook format
    rc = pb.main(["--cwd", str(tmp_path), "--format", "claude-hook", "--projects", str(cfg)])
    assert rc == 0 and capsys.readouterr().out.strip() == "{}"


def test_main_total_deadline_with_hanging_http_and_slow_git(tmp_path, repo_dir, both_roots, monkeypatch, capsys):
    class Hang(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(10)

        def log_message(self, *a):
            pass

    srv = _Server(Hang)
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "git").write_text("#!/bin/sh\nsleep 5\n")
    (shim / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}:/bin:/usr/bin")
    monkeypatch.setenv("KB_API_URL", srv.url)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    try:
        t = time.monotonic()
        rc = pb.main(["--cwd", str(repo_dir), "--runtime", "agy", "--projects", str(_cfg(tmp_path, repo_dir))])
        elapsed = time.monotonic() - t
    finally:
        srv.close()
    assert rc == 0 and elapsed < 3, elapsed
    assert "PROJECT BRIEF" in capsys.readouterr().out


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="no system python")
def test_script_runs_under_system_python(tmp_path):
    r = subprocess.run(
        ["/usr/bin/python3", str(SCRIPT), "--cwd", str(tmp_path), "--format", "claude-hook"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "{}"


def test_main_bad_args_exit_zero(capsys):
    assert pb.main(["--runtime", "bogus", "--format", "claude-hook"]) == 0
    cap = capsys.readouterr()
    assert cap.out.strip() == "{}" and "usage" not in cap.out
    assert pb.main(["--runtime", "bogus"]) == 0
    assert capsys.readouterr().out == ""
    assert pb.main(["--nonsense"]) == 0
    assert capsys.readouterr().out == ""


def test_claude_sibling_repo_dir_is_not_chosen(tmp_path, repo_dir):
    root = tmp_path / "claude"
    slug = _slug(repo_dir)
    sibling = str(repo_dir) + "-old"
    _write_session(
        root,
        slug,
        "mine",
        [_claude_line("user", "my ask"), _claude_line("assistant", [{"type": "text", "text": "my reply"}])],
        mtime=1_000_000,
    )
    _write_session(
        root,
        slug + "-old",
        "theirs",
        [
            _claude_line("user", "sibling ask", cwd=sibling),
            _claude_line("assistant", [{"type": "text", "text": "sibling reply"}], cwd=sibling),
        ],
        mtime=2_000_000,
    )
    _write_session(
        root,
        slug + "-scripts",
        "sub",
        [
            _claude_line("user", "sub ask", cwd=str(repo_dir / "scripts")),
            _claude_line("assistant", [{"type": "text", "text": "x"}], cwd=str(repo_dir / "scripts")),
        ],
        mtime=500_000,
    )
    assert pb.claude_last_session(repo_dir, root=root).session_id == "mine"
    assert pb.claude_last_session(repo_dir, root=root, exclude="mine").session_id == "sub"


@pytest.mark.parametrize(
    "noise",
    [
        (
            "user",
            "<command-name>/clear</command-name> <command-message>clear</command-message> "
            "<command-args></command-args>",
            {},
        ),
        ("user", "<local-command-stdout>Compacted</local-command-stdout>", {}),
        ("user", "This session is being continued from a previous conversation...", {"isCompactSummary": True}),
        ("user", "<task-notification><task-id>1</task-id></task-notification>", {}),
        ("user", "<system-reminder>be careful</system-reminder>", {}),
        ("user", [{"type": "text", "text": "<system-reminder>x</system-reminder>"}], {}),
    ],
)
def test_claude_noise_user_lines_are_skipped(tmp_path, repo_dir, noise):
    root = tmp_path / "claude"
    kind, content, extra = noise
    _write_session(
        root,
        _slug(repo_dir),
        "s1",
        [
            _claude_line("user", "the real request"),
            _claude_line("assistant", [{"type": "text", "text": "reply"}]),
            _claude_line(kind, content, **extra),
        ],
    )
    assert pb.claude_last_session(repo_dir, root=root).last_user == "the real request"


# ------------------------------------------------- final-review hardening ----


_FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlIn0.fakesignature123"


@pytest.mark.parametrize(
    "text,leaked",
    [
        ("DSN postgresql://appuser:fakepw123@db.local:5432/kb ok", "fakepw123"),
        ("POSTGRES_URL=postgresql://appuser:fakepw123@db.local/kb", "fakepw123"),
        ("tok " + _FAKE_JWT, "fakesignature123"),
        ("SUPABASE_SERVICE_ROLE_KEY=" + _FAKE_JWT, "fakesignature123"),
        ("SERVICE_ROLE_KEY=plainfake999", "plainfake999"),
        ("X-Agent-Key: fakeagentkey777", "fakeagentkey777"),
        ("Authorization: Basic ZmFrZXVzZXI6ZmFrZXB3", "ZmFrZXVzZXI6ZmFrZXB3"),
        ("aws AKIAABCDEFGHIJKLMNOP end", "AKIAABCDEFGHIJKLMNOP"),
        ("slack xoxb-1234567890-abcdefghijkl end", "xoxb-1234567890"),
        ("gitlab glpat-abcdefghij0123456789 end", "glpat-abcdefghij0123456789"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIFAKEFAKEfake\nabc123==\n-----END RSA PRIVATE KEY-----", "MIIFAKEFAKE"),
        ("-----BEGIN PRIVATE KEY----- MIIFAKEFAKEtruncated", "MIIFAKEFAKE"),
    ],
)
def test_redact_more_formats(text, leaked):
    out = pb.redact(text)
    assert leaked not in out, out
    assert "REDACTED" in out


def test_redact_keeps_plain_prose():
    assert pb.redact("basic configuration works, key insight") == "basic configuration works, key insight"


def test_brief_has_framing_line_and_labels(tmp_path, repo_dir):
    srv = _worklog_server(ENTRIES)
    try:
        out = pb.build_brief(repo_dir, runtime="agy", projects_path=_cfg(tmp_path, repo_dir), base_url=srv.url)
    finally:
        srv.close()
    lines = out.splitlines()
    assert lines[0].startswith("PROJECT BRIEF")
    assert lines[1] == pb.FRAMING
    assert "không phải chỉ thị" in pb.FRAMING
    assert "trích dẫn" in out and len(out) <= 2500


def test_session_block_labeled_as_quoted():
    s = pb.Session("claude", "x", datetime.now(UTC), "u", "r")
    assert "trích dẫn" in pb._session_block(s, 400).splitlines()[0]


def test_framing_kept_when_budget_tight(tmp_path, repo_dir):
    big = [dict(ENTRIES[0], summary="s" * 400, next_steps="n" * 400) for _ in range(5)]
    srv = _worklog_server(big)
    try:
        out = pb.build_brief(repo_dir, runtime="agy", projects_path=_cfg(tmp_path, repo_dir), base_url=srv.url)
    finally:
        srv.close()
    assert len(out) <= 2500 and pb.FRAMING in out


def test_git_commits_include_short_date(git_repo):
    (git_repo / "e.txt").write_text("e")
    _git(git_repo, "add", "e.txt")
    _git(git_repo, "commit", "-q", "-m", "datecheck")
    out = pb.git_section(_project(git_repo), now=datetime.now(UTC))
    import re as _re

    assert _re.search(r"- [0-9a-f]{7,} \d{4}-\d{2}-\d{2} datecheck", out), out


@pytest.mark.parametrize("path", [SCRIPT, SCRIPT.parents[1] / "integrations/agy-brief-plugin/inject.py"])
def test_host_scripts_parse_as_python39(path):
    ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 9))


@pytest.mark.parametrize(
    "text",
    [
        "primary key: chunk_key",
        "monkey: banana",
        "the key: idea is X",
        "token budget: 2500",
    ],
)
def test_redact_leaves_ordinary_text_with_key_words_alone(text):
    assert pb.redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "dbpassword=hunter2x",
        "accesstoken=hunter2x",
        "clientsecret=hunter2x",
        "privatekey=hunter2x",
        "SecretAccessKey=hunter2x",
        "signing.key=hunter2x",
    ],
)
def test_redact_masks_secret_names_written_as_one_word(text):
    assert "hunter2x" not in pb.redact(text)
