"""scripts/worklog_guard.py: the Claude Stop hook that makes a turn which changed code leave a worklog entry.

Measured 2026-10-27: of the sessions that changed code since 24/10, MyNotch logged 3 of 7, CyberOS 0 of 1, and AGY
conversations almost never: a prompt rule is not enough, so the hook asks once, then writes the entry itself.
"""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/worklog_guard.py"
_spec = importlib.util.spec_from_file_location("worklog_guard", SCRIPT)
wg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wg)


def user(text, ts="2026-10-27T01:00:00Z"):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}


def tool_result(ts="2026-10-27T01:00:05Z"):
    return {"type": "user", "timestamp": ts, "message": {"content": [{"type": "tool_result", "tool_use_id": "t"}]}}


def tool(name, ts="2026-10-27T01:00:03Z", **inp):
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]},
    }


def reply(text, ts="2026-10-27T01:00:09Z"):
    return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}}


def transcript(tmp_path, *entries):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


@pytest.fixture
def projects(tmp_path):
    repo = tmp_path / "MyNotch"
    repo.mkdir()
    config = tmp_path / "projects.json"
    config.write_text(json.dumps({"MyNotch": {"repo": str(repo), "git_author": "a@b.c"}}))
    return config, repo


def hook(path, repo, active=False):
    return {"session_id": "s1", "transcript_path": str(path), "cwd": str(repo), "stop_hook_active": active}


def test_a_turn_that_only_read_and_answered_may_stop(tmp_path, projects):
    config, repo = projects
    path = transcript(tmp_path, user("giải thích hàm x"), tool("Read", file_path="a.py"), tool_result(), reply("đây"))

    assert wg.decide(hook(path, repo), config, post=None) is None


def test_a_turn_that_edited_code_without_logging_is_held_once(tmp_path, projects):
    config, repo = projects
    path = transcript(
        tmp_path, user("sửa lỗi"), tool("Edit", file_path=str(repo / "a.py")), tool_result(), reply("xong")
    )

    verdict = wg.decide(hook(path, repo), config, post=None)

    assert verdict["decision"] == "block"
    assert "log_progress" in verdict["reason"] and "MyNotch" in verdict["reason"]
    assert "propose_knowledge_update" in verdict["reason"]  # specs: a reminder, the human gate decides


def test_a_commit_counts_as_a_change(tmp_path, projects):
    config, repo = projects
    path = transcript(tmp_path, user("commit"), tool("Bash", command="git commit -m x"), tool_result(), reply("ok"))

    assert wg.decide(hook(path, repo), config, post=None)["decision"] == "block"


def test_a_turn_that_logged_its_progress_may_stop(tmp_path, projects):
    config, repo = projects
    path = transcript(
        tmp_path,
        user("sửa lỗi"),
        tool("Edit", file_path=str(repo / "a.py")),
        tool_result(),
        tool("mcp__personal-kb__log_progress", project="MyNotch", summary="s"),
        tool_result(),
        reply("xong"),
    )

    assert wg.decide(hook(path, repo), config, post=None) is None


def test_only_the_last_turn_counts(tmp_path, projects):
    # an edit logged in an earlier turn does not excuse an unlogged edit now, and an earlier edit does not hold a reply
    config, repo = projects
    earlier = [user("a", "2026-10-27T00:00:00Z"), tool("Edit", "2026-10-27T00:00:01Z", file_path="a.py"), tool_result()]
    path = transcript(tmp_path, *earlier, user("cảm ơn"), reply("ok"))

    assert wg.decide(hook(path, repo), config, post=None) is None


def test_a_repo_outside_the_project_map_is_left_alone(tmp_path, projects):
    config, _ = projects
    other = tmp_path / "other"
    other.mkdir()
    path = transcript(tmp_path, user("sửa"), tool("Write", file_path=str(other / "a.py")), tool_result(), reply("ok"))

    assert wg.decide(hook(path, other), config, post=None) is None


def test_when_held_once_and_still_unlogged_the_hook_writes_the_entry_itself(tmp_path, projects):
    config, repo = projects
    path = transcript(
        tmp_path,
        user("sửa lỗi notch"),
        tool("Edit", file_path=str(repo / "Notch.swift")),
        tool_result(),
        reply("Đã sửa."),
    )
    posted = []

    verdict = wg.decide(hook(path, repo, active=True), config, post=posted.append)

    assert verdict is None
    [entry] = posted
    assert entry["project"] == "MyNotch" and entry["kind"] == "progress" and entry["session_id"] == "s1"
    assert (
        entry["summary"].startswith("[tự động]") and "Notch.swift" in entry["summary"] and "Đã sửa." in entry["summary"]
    )
    assert "sửa lỗi notch" in entry["summary"]


def test_an_unreadable_transcript_never_holds_the_agent(tmp_path, projects):
    config, repo = projects

    assert wg.decide(hook(tmp_path / "missing.jsonl", repo), config, post=None) is None


def test_the_fallback_posts_to_the_worklog_api(tmp_path):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(201)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        wg.post_worklog({"project": "P", "summary": "s"}, base_url=f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()

    assert received == [("/api/v1/agent/worklog", {"project": "P", "summary": "s"})]


def test_the_hook_runs_on_the_system_python():
    # the hook command is /usr/bin/python3 (3.9 on macOS): newer syntax there crashes every stop
    import shutil
    import subprocess

    if not shutil.which("/usr/bin/python3"):
        pytest.skip("no /usr/bin/python3")
    done = subprocess.run(["/usr/bin/python3", str(SCRIPT)], input="{}", capture_output=True, text=True, timeout=20)

    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


def test_a_file_changed_through_bash_is_seen_through_git(tmp_path, projects):
    # edits made with a shell command (heredoc, sed -i, a script) never show as Edit/Write tool calls
    import subprocess

    config, repo = projects
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "tracked.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    started = "2026-01-01T00:00:00Z"  # before the edit below
    (repo / "tracked.py").write_text("x = 2\n")
    path = transcript(tmp_path, user("sửa", started), tool("Bash", command="sed -i '' s/1/2/ tracked.py"), reply("ok"))

    verdict = wg.decide(hook(path, repo), config, post=None)

    assert verdict is not None and verdict["decision"] == "block"


def test_files_changed_before_the_turn_do_not_hold_it(tmp_path, projects):
    import subprocess

    config, repo = projects
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "old.py").write_text("x = 1\n")  # uncommitted, but older than the turn
    path = transcript(tmp_path, user("giải thích", "2999-01-01T00:00:00Z"), reply("ok"))

    assert wg.decide(hook(path, repo), config, post=None) is None


# --- Antigravity (AGY): same rule, its own transcript and Stop contract (decision "continue") ---


def agy_step(kind, ts="2026-10-27T01:00:03Z", source="MODEL", **fields):
    return {"source": source, "type": kind, "status": "DONE", "created_at": ts, **fields}


def agy_user(text, ts="2026-10-27T01:00:00Z", source="USER_EXPLICIT"):
    return agy_step("USER_INPUT", ts, source=source, content=f"<USER_REQUEST>\n{text}\n</USER_REQUEST>")


def agy_call(name, ts="2026-10-27T01:00:03Z", **args):
    return agy_step(
        "PLANNER_RESPONSE", ts, tool_calls=[{"name": name, "args": {k: json.dumps(v) for k, v in args.items()}}]
    )


def agy_reply(text, ts="2026-10-27T01:00:09Z"):
    return agy_step("PLANNER_RESPONSE", ts, content=text)


def agy_hook(path, repo, execution=0, reason="NO_TOOL_CALL"):
    return {
        "conversationId": "c1",
        "workspacePaths": [str(repo)],
        "transcriptPath": str(path),
        "executionNum": execution,
        "terminationReason": reason,
        "lastUserInput": "sửa lỗi",
    }


def test_an_agy_turn_that_edited_without_logging_is_continued_once(tmp_path, projects):
    config, repo = projects
    path = transcript(tmp_path, agy_user("sửa lỗi"), agy_call("edit_file", Path=str(repo / "a.py")), agy_reply("xong"))

    verdict = wg.decide(agy_hook(path, repo), config, post=None)

    assert verdict["decision"] == "continue"
    assert (
        "call_mcp_tool" in verdict["reason"] and "log_progress" in verdict["reason"] and "MyNotch" in verdict["reason"]
    )


def test_an_agy_turn_that_called_log_progress_may_stop(tmp_path, projects):
    config, repo = projects
    path = transcript(
        tmp_path,
        agy_user("sửa lỗi"),
        agy_call("write_file", Path=str(repo / "a.py"), Content="x"),
        agy_call("call_mcp_tool", ServerName="personal-kb", ToolName="log_progress", Arguments="{}"),
        agy_reply("xong"),
    )

    assert wg.decide(agy_hook(path, repo), config, post=None) is None


def test_an_agy_commit_counts_and_the_injected_brief_is_not_a_prompt(tmp_path, projects):
    # the brief plugin injects a USER_INPUT from SYSTEM_SDK: it must not start a new turn
    config, repo = projects
    path = transcript(
        tmp_path,
        agy_user("commit đi"),
        agy_call("run_command", CommandLine="git commit -m x"),
        agy_user("PROJECT BRIEF — MyNotch", source="SYSTEM_SDK"),
        agy_reply("ok"),
    )

    assert wg.decide(agy_hook(path, repo), config, post=None)["decision"] == "continue"


def test_agy_asked_once_already_gets_the_entry_written_for_it(tmp_path, projects):
    config, repo = projects
    path = transcript(
        tmp_path, agy_user("sửa notch"), agy_call("edit_file", Path=str(repo / "N.swift")), agy_reply("Xong.")
    )
    posted = []

    assert wg.decide(agy_hook(path, repo, execution=1), config, post=posted.append) is None
    [entry] = posted
    assert entry["agent"] == "agy (hook)" and entry["session_id"] == "c1" and "N.swift" in entry["summary"]
    assert "sửa notch" in entry["summary"] and "<USER_REQUEST>" not in entry["summary"]


def test_an_agy_stop_that_was_cancelled_or_failed_is_left_alone(tmp_path, projects):
    config, repo = projects
    path = transcript(tmp_path, agy_user("sửa"), agy_call("edit_file", Path=str(repo / "a.py")), agy_reply("x"))

    for reason in ("USER_CANCELED", "ERROR", "MAX_INVOCATIONS"):
        assert wg.decide(agy_hook(path, repo, reason=reason), config, post=None) is None


def test_the_agy_hook_answers_with_a_json_object_on_the_system_python(tmp_path, projects):
    # AGY reads a JSON object from stdout: "{}" lets the agent stop
    import subprocess

    done = subprocess.run(
        ["/usr/bin/python3", str(SCRIPT)],
        input=json.dumps({"conversationId": "c", "workspacePaths": [str(tmp_path)], "transcriptPath": "/nope"}),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert (done.returncode, done.stdout.strip(), done.stderr) == (0, "{}", "")


def test_rca_turn_with_only_progress_log_is_held_for_gotcha(tmp_path, projects):
    config, repo = projects
    # Lượt điều tra RCA mất quyền TCC nhưng chỉ ghi log_progress(kind="progress") -> hook vẫn chặn để nhắc gotcha
    path = transcript(
        tmp_path,
        user("tại sao ứng dụng bị mất quyền TCC sau khi build?"),
        tool("Bash", command="codesign -dv /Applications/MyNotch.app"),
        tool_result(),
        tool("Edit", file_path=str(repo / "Build.swift")),
        tool_result(),
        tool("mcp__personal-kb__log_progress", project="MyNotch", kind="progress", summary="Sửa build"),
        tool_result(),
        reply("Đã tìm ra nguyên nhân gốc: do ad-hoc signing và cp -R làm hỏng Designated Requirement."),
    )

    verdict = wg.decide(hook(path, repo), config, post=None)

    assert verdict["decision"] == "block"
    assert "gotcha" in verdict["reason"].lower()
    assert "propose_knowledge_update" in verdict["reason"]


def test_rca_turn_without_code_changes_is_still_held_for_gotcha(tmp_path, projects):
    config, repo = projects
    # Lượt điều tra RCA không sửa code nhưng tìm ra nguyên nhân gốc -> vẫn được nhắc nhở lưu gotchas
    path = transcript(
        tmp_path,
        user("kiểm tra lỗi"),
        tool("Bash", command="codesign -dv /Applications/MyNotch.app"),
        tool_result(),
        reply("Nguyên nhân cốt lõi là do ad-hoc signing phá vỡ Designated Requirement."),
    )

    verdict = wg.decide(hook(path, repo), config, post=None)

    assert verdict["decision"] == "block"
    assert "gotcha" in verdict["reason"].lower()


def test_rca_turn_with_gotcha_log_or_proposal_may_stop(tmp_path, projects):
    config, repo = projects
    # Đã ghi log_progress(kind="gotcha") -> cho phép dừng
    path_logged = transcript(
        tmp_path,
        user("kiểm tra nguyên nhân gốc"),
        tool("Bash", command="codesign -dv /Applications/MyNotch.app"),
        tool_result(),
        tool("mcp__personal-kb__log_progress", project="MyNotch", kind="gotcha", summary="RCA TCC"),
        tool_result(),
        reply("Xong."),
    )
    assert wg.decide(hook(path_logged, repo), config, post=None) is None

    # Hoặc đã gọi propose_knowledge_update -> cho phép dừng
    path_proposed = transcript(
        tmp_path,
        user("kiểm tra nguyên nhân gốc"),
        tool("Bash", command="codesign -dv /Applications/MyNotch.app"),
        tool_result(),
        tool("mcp__personal-kb__propose_knowledge_update", project="MyNotch", title="TCC Gotcha"),
        tool_result(),
        reply("Xong."),
    )
    assert wg.decide(hook(path_proposed, repo), config, post=None) is None


def test_rca_fallback_records_kind_gotcha(tmp_path, projects):
    config, repo = projects
    path = transcript(
        tmp_path,
        user("tìm nguyên nhân gốc rễ lỗi"),
        tool("Bash", command="codesign -dv /Applications/MyNotch.app"),
        tool_result(),
        reply("Nguyên nhân gốc rễ là ad-hoc signing."),
    )
    posted = []

    assert wg.decide(hook(path, repo, active=True), config, post=posted.append) is None
    [entry] = posted
    assert entry["kind"] == "gotcha"
    assert "[tự động RCA/Gotcha]" in entry["summary"]
