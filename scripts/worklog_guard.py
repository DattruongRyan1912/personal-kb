#!/usr/bin/env python3
"""Stop hook for Claude Code and Antigravity (AGY): a turn that changed code in a mapped repo leaves a worklog entry.

A prompt rule alone was not enough: of the sessions that changed code since 2026-10-24, MyNotch logged 3 of 7 and
CyberOS 0 of 1. So when the last turn edited files or committed without calling log_progress, the hook holds the stop
once and asks the agent to log (and to propose any spec its change made wrong). If the agent stops again still without
logging, the hook writes a minimal entry itself through the worklog API. Claude marks the second stop with
stop_hook_active and is held with {"decision": "block"}. AGY counts the stops of a turn in executionNum (0 on the
first), is held with {"decision": "continue"} (its hooks.json Stop contract) and reads "{}" as "let it stop".

Stdlib only, runs on /usr/bin/python3 (3.9). Never fails the agent: any error lets the stop through.
Claude settings: {"hooks": {"Stop": [{"hooks": [{"type": "command", "command":
  "/usr/bin/python3 <repo>/scripts/worklog_guard.py", "timeout": 10}]}]}}
AGY plugin hooks.json: {"kb-brief": {"Stop": [{"type": "command", "command": "...same...", "timeout": 10}]}}
"""

from __future__ import annotations  # /usr/bin/python3 is 3.9: annotations stay strings

import json
import os
import re
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_brief as pb  # noqa: E402  (shared: project map, transcript parsing, git)

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
AGY_EDIT_TOOLS = {"edit_file", "write_file"}
AGY_NORMAL_STOP = {"", "NO_TOOL_CALL"}  # cancelled, failed or out of budget: not the time to ask for anything
SUMMARY_MAX = 1900
POST_TIMEOUT = 3.0

_RCA_TEXT_RE = re.compile(
    r"\b(rca|root[\s_-]?cause|nguyên nhân gốc|nguyên nhân cốt lõi|cạm bẫy|gotcha|post[\s_-]?mortem|"
    r"designated requirement|ad[\s_-]?hoc signing|code[\s_-]?sign(?:ature)?|cdhash|tccutil|"
    r"sigkill|deadlock|race condition|desync|hỏng chữ ký|mất quyền tcc)\b",
    re.IGNORECASE,
)
_RCA_CMD_RE = re.compile(
    r"\b(codesign\s+-[dv]|spctl\s+--assess|tccutil\b|security\s+find-identity)",
    re.IGNORECASE,
)


class Turn:
    def __init__(self) -> None:
        self.prompt = ""
        self.started_at = ""
        self.files: list[str] = []
        self.committed = False
        self.logged = False
        self.reply = ""
        self.gotcha_logged = False
        self.gotcha_proposed = False
        self.rca_command = False

    @property
    def changed(self) -> bool:
        return bool(self.files) or self.committed

    @property
    def is_rca(self) -> bool:
        return bool(
            self.rca_command
            or _RCA_TEXT_RE.search(self.prompt)
            or _RCA_TEXT_RE.search(self.reply)
        )

    @property
    def gotcha_captured(self) -> bool:
        return bool(
            self.gotcha_logged
            or self.gotcha_proposed
            or any("gotcha" in f.lower() for f in self.files)
        )


def _prompt_text(obj: dict) -> str:
    """The text of a prompt the person typed; '' for tool results, reminders-only and command noise."""
    if obj.get("type") != "user" or obj.get("isSidechain") or obj.get("isMeta"):
        return ""
    text = pb._REMINDER.sub("", pb._claude_text(obj.get("message"))).strip()
    return "" if not text or pb._is_noise_user(obj, text) else text


def last_turn(transcript: Path) -> Turn:
    """What the Claude agent did since the last prompt the person typed."""
    turn = Turn()
    with open(transcript, encoding="utf-8", errors="replace") as lines:
        for raw in lines:
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            prompt = _prompt_text(obj)
            if prompt:
                turn = Turn()
                turn.prompt, turn.started_at = prompt, str(obj.get("timestamp") or "")
                continue
            if obj.get("type") != "assistant" or obj.get("isSidechain"):
                continue
            content = (obj.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    turn.reply = block["text"].strip()
                if block.get("type") != "tool_use":
                    continue
                name, args = str(block.get("name", "")), block.get("input") or {}
                if name in EDIT_TOOLS and args.get("file_path"):
                    fpath = str(args.get("file_path") or args.get("notebook_path"))
                    turn.files.append(fpath)
                    if "gotcha" in fpath.lower():
                        turn.gotcha_proposed = True
                elif name == "Bash":
                    cmd = str(args.get("command", ""))
                    if "git commit" in cmd:
                        turn.committed = True
                    if _RCA_CMD_RE.search(cmd):
                        turn.rca_command = True
                elif name.endswith("log_progress"):
                    turn.logged = True
                    if str(args.get("kind") or "").strip().lower() == "gotcha":
                        turn.gotcha_logged = True
                elif name.endswith("propose_knowledge_update"):
                    turn.gotcha_proposed = True
    return turn


def _agy_dict(value: object) -> dict:
    """AGY may pass Arguments as dict, or as a JSON string (possibly escaped)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, str):
                nested = json.loads(parsed)
                if isinstance(nested, dict):
                    return nested
        except Exception:
            return {}
    return {}


def _agy_arg(value: object) -> str:
    """AGY stores each tool argument JSON-encoded: '"personal-kb"' is personal-kb."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        return decoded if isinstance(decoded, str) else value
    return "" if value is None else str(value)


def agy_turn(transcript: Path) -> Turn:
    """What the AGY agent did since the last prompt the person typed: USER_EXPLICIT input, not the SYSTEM_SDK brief
    or the hook's SYSTEM_MESSAGE."""
    turn = Turn()
    with open(transcript, encoding="utf-8", errors="replace") as lines:
        for raw in lines:
            try:
                step = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(step, dict):
                continue
            if step.get("type") == "USER_INPUT" and step.get("source") == "USER_EXPLICIT":
                turn = Turn()
                text = str(step.get("content") or "")
                turn.prompt = text.replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "").strip()
                turn.started_at = str(step.get("created_at") or "")
                continue
            if step.get("source") != "MODEL" or step.get("type") != "PLANNER_RESPONSE":
                continue
            if str(step.get("content") or "").strip():
                turn.reply = str(step["content"]).strip()
            for call in step.get("tool_calls") or []:
                name, args = str(call.get("name", "")), call.get("args") or {}
                if name in AGY_EDIT_TOOLS and args.get("Path"):
                    fpath = _agy_arg(args["Path"])
                    turn.files.append(fpath)
                    if "gotcha" in fpath.lower():
                        turn.gotcha_proposed = True
                elif name == "run_command":
                    cmd = _agy_arg(args.get("CommandLine"))
                    if "git commit" in cmd:
                        turn.committed = True
                    if _RCA_CMD_RE.search(cmd):
                        turn.rca_command = True
                elif name == "call_mcp_tool":
                    tool_name = _agy_arg(args.get("ToolName"))
                    if tool_name.endswith("log_progress"):
                        turn.logged = True
                        mcp_args = _agy_dict(args.get("Arguments"))
                        if str(mcp_args.get("kind") or "").strip().lower() == "gotcha":
                            turn.gotcha_logged = True
                    elif tool_name.endswith("propose_knowledge_update"):
                        turn.gotcha_proposed = True
    return turn


def _reason(project: str, runtime: str = "claude", rca: bool = False, changed: bool = True) -> str:
    how = (
        '`call_mcp_tool` với ServerName "personal-kb", ToolName "log_progress"'
        if runtime == "agy"
        else "MCP personal-kb `log_progress`"
    )
    if rca and changed:
        lead = (
            f"Lượt này đã điều tra lỗi / nguyên nhân gốc rễ (RCA) và sửa code trong {project} nhưng chưa nạp cạm bẫy vào kho tri thức. "
            "Trước khi kết thúc:"
        )
    elif rca:
        lead = (
            f"Lượt này đã phát hiện cạm bẫy kỹ thuật / nguyên nhân gốc rễ (RCA) trong {project} nhưng chưa lưu trữ. "
            "Trước khi kết thúc:"
        )
    else:
        lead = f"Lượt này đã sửa code trong {project} nhưng chưa ghi worklog. Trước khi kết thúc:"

    if rca:
        step1 = (
            f'1. Gọi {how} với project="{project}", kind="gotcha", summary: nguyên nhân gốc rễ (RCA) và cạm bẫy kỹ thuật, '
            "next_steps: việc tiếp theo."
        )
        step2 = (
            f"2. Nạp cạm bẫy vào `{project.upper()}-GOTCHAS.md` bằng cách cập nhật trực tiếp "
            f"`knowledge/{project.upper()}-GOTCHAS.md` hoặc qua `propose_knowledge_update` (hệ thống tự động áp dụng)."
        )
    else:
        step1 = (
            f'1. Gọi {how} với project="{project}", kind "progress" (hoặc "handoff" nếu '
            "dừng phiên), summary: đã làm gì và vì sao, next_steps: việc còn dở."
        )
        step2 = (
            f"2. Nếu thay đổi làm một spec của {project} trong Personal-KB không còn đúng, hãy cập nhật trực tiếp "
            f"`knowledge/` hoặc qua `propose_knowledge_update` (tự động áp dụng vào tài liệu, không cần chờ duyệt)."
        )

    return (
        f"{lead}\n"
        f"{step1}\n"
        f"{step2}\n"
        "Nếu MCP không dùng được, nói rõ một câu rồi kết thúc: hook sẽ tự ghi một mục tối thiểu."
    )


def _git(repo: Path, *args: str) -> str:
    try:
        return pb._run_git(repo, *args)
    except Exception:  # noqa: BLE001 - not a repo, git missing or slow: the entry is written without it
        return ""


def _changed_since(repo: Path, started_at: str) -> list[str]:
    """Files git sees as changed (tracked or new) and written after the turn began: catches edits made with shell
    commands, which never show as Edit/Write tool calls."""
    start = pb._parse_dt(started_at)
    if start is None:
        return []
    since = start.timestamp()
    changed = []
    for line in _git(repo, "status", "--porcelain", "--untracked-files=all").splitlines():
        name = line[3:].split(" -> ")[-1].strip().strip('"')
        path = repo / name
        try:
            if name and path.is_file() and path.stat().st_mtime >= since:
                changed.append(str(path))
        except OSError:
            continue
    return changed


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fallback(project: pb.Project, turn: Turn, session_id: str, runtime: str = "claude") -> dict:
    names = []
    for f in turn.files:
        path = Path(f)
        rel = str(path.relative_to(project.repo)) if path.is_absolute() and project.repo in path.parents else path.name
        if rel not in names:
            names.append(rel)
    commits = []
    if turn.started_at:
        log = _git(project.repo, "log", f"--since={turn.started_at}", "--format=%s", "-n", "5")
        commits = [line for line in log.splitlines() if line.strip()]
    lead_tag = "[tự động RCA/Gotcha]" if turn.is_rca else "[tự động]"
    parts = [f"{lead_tag} Phiên kết thúc mà agent không ghi worklog.", f"Yêu cầu: {_short(turn.prompt, 200)}"]
    if names:
        parts.append(f"Đã sửa: {', '.join(names[:8])}{f' (+{len(names) - 8})' if len(names) > 8 else ''}")
    if commits:
        parts.append(f"Commit: {'; '.join(_short(c, 80) for c in commits)}")
    if turn.reply:
        parts.append(f"Kết: {_short(turn.reply, 300)}")
    branch = _git(project.repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    return {
        "project": project.name,
        "kind": "gotcha" if turn.is_rca else "progress",
        "summary": _short(" | ".join(parts), SUMMARY_MAX),
        "next_steps": "",
        "agent": f"{runtime} (hook)",
        "session_id": session_id,
        "branch": branch,
    }


def decide(hook: dict, config: Path, post: Callable[[dict], object] | None) -> dict | None:
    """The Stop hook's verdict: Claude {"decision": "block", ...} / AGY {"decision": "continue", ...} to hold the
    stop, None to let it through."""
    runtime = "agy" if "transcriptPath" in hook else "claude"
    if runtime == "agy":
        if str(hook.get("terminationReason") or "") not in AGY_NORMAL_STOP:
            return None
        cwd, transcript = (hook.get("workspacePaths") or ["."])[0], hook.get("transcriptPath")
        asked, session_id = int(hook.get("executionNum") or 0) > 0, str(hook.get("conversationId") or "")
    else:
        cwd, transcript = hook.get("cwd") or ".", hook.get("transcript_path")
        asked, session_id = bool(hook.get("stop_hook_active")), str(hook.get("session_id") or "")
    try:
        project = pb.resolve_project(Path(cwd), pb.load_projects(config))
        if project is None or not transcript:
            return None
        turn = (agy_turn if runtime == "agy" else last_turn)(Path(transcript))
    except (OSError, KeyError, ValueError, TypeError):
        return None

    turn.files += [f for f in _changed_since(project.repo, turn.started_at) if f not in turn.files]
    needs_worklog = turn.changed and not turn.logged
    needs_gotcha = turn.is_rca and not turn.gotcha_captured
    if not needs_worklog and not needs_gotcha:
        return None
    if not asked:
        return {
            "decision": "continue" if runtime == "agy" else "block",
            "reason": _reason(project.name, runtime, rca=needs_gotcha, changed=needs_worklog),
        }
    if post is not None and not turn.logged:  # asked once already: write the entry rather than hold the agent again
        post(_fallback(project, turn, session_id, runtime))
    return None


def post_worklog(entry: dict, *, base_url: str) -> None:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/v1/agent/worklog",
        data=json.dumps(entry).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=POST_TIMEOUT).read()
    except OSError:
        pass  # the KB is down: nothing to do, the stop goes through


def main() -> None:
    try:
        hook = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return
    base_url = os.environ.get("KB_API_URL", pb.DEFAULT_BASE_URL)
    verdict = decide(hook, pb.DEFAULT_PROJECTS, post=lambda entry: post_worklog(entry, base_url=base_url))
    if verdict:
        print(json.dumps(verdict, ensure_ascii=False))  # noqa: T201 - the hook answers on stdout
    elif "transcriptPath" in hook:
        print("{}")  # noqa: T201 - AGY reads a JSON object: an empty one lets the agent stop


if __name__ == "__main__":
    main()
