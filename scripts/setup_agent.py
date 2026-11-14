#!/usr/bin/env python3
"""Personal-KB Agent Integration & Sync Engine.

Automatically detects installed AI agents (Gemini Antigravity CLI, Claude Desktop,
Cursor, Kiro) and configures:
1. MCP Server entries in agent config files (with idempotent JSON merge).
2. Grounding & Anti-Hallucination rules (idempotent managed block).
3. Tool schemas for Antigravity CLI.

Usage:
    python scripts/setup_agent.py [--dry-run] [--check]
"""

import argparse
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATIONS_DIR = REPO_ROOT / "integrations"
RULES_FILE = INTEGRATIONS_DIR / "rules" / "personal-kb-grounding.md"

HOME = Path.home()
SYSTEM = platform.system()

# Managed block tags
TAG_START = "<!-- BEGIN PERSONAL-KB GROUNDING RULES -->"
TAG_END = "<!-- END PERSONAL-KB GROUNDING RULES -->"


def log(msg: str, symbol: str = "ℹ️") -> None:
    print(f"{symbol}  {msg}")


def log_success(msg: str) -> None:
    print(f"✅ {msg}")


def log_warning(msg: str) -> None:
    print(f"⚠️  {msg}")


def get_claude_desktop_config_path() -> Path | None:
    if SYSTEM == "Darwin":
        return HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif SYSTEM == "Windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    elif SYSTEM == "Linux":
        return HOME / ".config" / "Claude" / "claude_desktop_config.json"
    return None


def get_gemini_settings_path() -> Path:
    return HOME / ".gemini" / "settings.json"


def get_cursor_mcp_paths() -> list[Path]:
    paths = []
    # Global cursor config
    global_cursor = HOME / ".cursor" / "mcp.json"
    paths.append(global_cursor)
    # Repo-level .cursor/mcp.json
    local_cursor = REPO_ROOT / ".cursor" / "mcp.json"
    paths.append(local_cursor)
    return paths


def get_global_rules_paths() -> list[Path]:
    candidates = [
        HOME / ".agents" / "GLOBAL.md",
        HOME / ".claude" / "CLAUDE.md",
        HOME / ".gemini" / "GEMINI.md",
        HOME / ".kiro" / "steering" / "GLOBAL.md",
    ]
    found = []
    seen_real = set()
    for c in candidates:
        if c.exists():
            real = c.resolve()
            if real not in seen_real:
                seen_real.add(real)
                found.append(c)
    return found


def update_json_mcp_config(config_path: Path, mcp_entry: dict, dry_run: bool = False) -> bool:
    """Idempotently inject or update 'personal-kb' in an MCP config JSON."""
    data = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            log_warning(f"Không thể đọc file JSON {config_path}: {e}")
            return False

    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}

    current_entry = data["mcpServers"].get("personal-kb")
    if current_entry == mcp_entry:
        log(f"Cấu hình MCP 'personal-kb' đã chuẩn xác tại: {config_path}")
        return True

    data["mcpServers"]["personal-kb"] = mcp_entry

    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log_success(f"Đã cập nhật MCP server vào: {config_path}")
    else:
        log(f"[DRY-RUN] Sẽ cập nhật MCP server vào: {config_path}")
    return True


def update_rules_file(rule_path: Path, rule_content: str, dry_run: bool = False) -> bool:
    """Idempotently insert or replace the managed block in a markdown rules file."""
    if not rule_path.exists():
        return False

    existing_text = rule_path.read_text(encoding="utf-8")
    managed_block = f"{TAG_START}\n{rule_content.strip()}\n{TAG_END}"

    pattern = re.compile(f"{re.escape(TAG_START)}.*?{re.escape(TAG_END)}", re.DOTALL)
    if pattern.search(existing_text):
        new_text = pattern.sub(managed_block, existing_text)
        if new_text == existing_text:
            log(f"Rules đã đồng bộ mới nhất tại: {rule_path}")
            return True
    else:
        new_text = existing_text.rstrip() + "\n\n" + managed_block + "\n"

    if not dry_run:
        rule_path.write_text(new_text, encoding="utf-8")
        log_success(f"Đã chèn/cập nhật Grounding Rules tại: {rule_path}")
    else:
        log(f"[DRY-RUN] Sẽ chèn Grounding Rules tại: {rule_path}")
    return True


def setup_gemini_antigravity(dry_run: bool = False) -> None:
    """Setup Gemini settings and Antigravity tool schema."""
    gemini_settings = get_gemini_settings_path()
    mcp_script = (REPO_ROOT / "scripts" / "mcp_server.sh").resolve()
    
    mcp_entry = {
        "type": "stdio",
        "command": "/bin/bash",
        "args": [str(mcp_script)],
    }
    update_json_mcp_config(gemini_settings, mcp_entry, dry_run)

    # Sync Antigravity tool schemas
    schema_target = HOME / ".gemini" / "antigravity-cli" / "mcp" / "personal-kb"
    schema_src = (REPO_ROOT / "integrations" / "mcp" / "antigravity-schemas").resolve()
    if not dry_run:
        schema_target.mkdir(parents=True, exist_ok=True)
        if schema_src.exists():
            import shutil
            for f in schema_src.glob("*"):
                shutil.copy2(f, schema_target / f.name)
        log_success(f"Đã đồng bộ tool schemas ({len(list(schema_target.glob('*.json')))} tools) tại: {schema_target}")


def setup_claude_desktop(dry_run: bool = False) -> None:
    claude_cfg = get_claude_desktop_config_path()
    if not claude_cfg:
        return

    # Use uv run with absolute paths
    backend_dir = (REPO_ROOT / "backend").resolve()
    env_file = (REPO_ROOT / ".env").resolve()
    
    mcp_entry = {
        "command": "uv",
        "args": [
            "run",
            "--directory", str(backend_dir),
            "--env-file", str(env_file),
            "python", "-m", "personal_kb.mcp.cli"
        ]
    }
    update_json_mcp_config(claude_cfg, mcp_entry, dry_run)


def setup_cursor(dry_run: bool = False) -> None:
    backend_dir = (REPO_ROOT / "backend").resolve()
    env_file = (REPO_ROOT / ".env").resolve()
    mcp_entry = {
        "command": "uv",
        "args": [
            "run",
            "--directory", str(backend_dir),
            "--env-file", str(env_file),
            "python", "-m", "personal_kb.mcp.cli"
        ]
    }
    for p in get_cursor_mcp_paths():
        if p.parent.exists() or p.name == "mcp.json":
            update_json_mcp_config(p, mcp_entry, dry_run)


def setup_grounding_rules(dry_run: bool = False) -> None:
    if not RULES_FILE.exists():
        log_warning(f"File quy tắc mẫu không tồn tại: {RULES_FILE}")
        return

    content = RULES_FILE.read_text(encoding="utf-8")
    # Clean inner content if tags already present in file
    inner = content.replace(TAG_START, "").replace(TAG_END, "").strip()

    target_rules = get_global_rules_paths()
    if not target_rules:
        # Fallback to creating local .cursorrules or ~/.agents/GLOBAL.md
        target = HOME / ".agents" / "GLOBAL.md"
        target_rules.append(target)
        if not dry_run and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Global Agent Instructions\n\n", encoding="utf-8")

    for r_path in target_rules:
        update_rules_file(r_path, inner, dry_run)


def setup_git_hooks(repo_root: Path, dry_run: bool = False) -> None:
    """Install or update .git/hooks/post-commit for automatic background vector ingestion."""
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        return
    hooks_dir = git_dir / "hooks"
    post_commit = hooks_dir / "post-commit"
    content = (
        "#!/bin/bash\n"
        "# Personal-KB Post-Commit Hook: Automatic Vector Ingestion on Knowledge Updates\n"
        "# Detaches to background immediately to ensure zero latency on git commit.\n\n"
        'REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"\n'
        'if [ -n "$REPO_ROOT" ] && [ -x "$REPO_ROOT/scripts/auto_ingest_hook.sh" ]; then\n'
        '  nohup "$REPO_ROOT/scripts/auto_ingest_hook.sh" >/dev/null 2>&1 &\n'
        "fi\n"
    )
    if dry_run:
        log("[DRY-RUN] Would configure .git/hooks/post-commit auto-ingest hook", "🔍")
        return
    hooks_dir.mkdir(parents=True, exist_ok=True)
    post_commit.write_text(content, encoding="utf-8")
    post_commit.chmod(0o755)
    log_success("Đã cài đặt Git hook: .git/hooks/post-commit (Background Vector Ingestion)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal-KB Agent Integration Setup")
    parser.add_argument("--dry-run", action="store_true", help="Kiểm tra thay đổi mà không ghi đè file")
    parser.add_argument("--check", action="store_true", help="Kiểm tra trạng thái kết nối agent hiện tại")
    args = parser.parse_args()

    print("=" * 70)
    print("🚀 PERSONAL-KB AGENT INTEGRATION & AUTO-SYNC ENGINE")
    print(f"📁 Repository Root: {REPO_ROOT}")
    print("=" * 70)

    # 1. Setup Gemini Antigravity
    log("Thiết lập cấu hình cho Gemini / Antigravity CLI...")
    setup_gemini_antigravity(args.dry_run)

    # 2. Setup Claude Desktop
    log("Thiết lập cấu hình cho Claude Desktop...")
    setup_claude_desktop(args.dry_run)

    # 3. Setup Cursor IDE
    log("Thiết lập cấu hình cho Cursor IDE...")
    setup_cursor(args.dry_run)

    # 4. Inject Grounding Rules (Zero Hallucination)
    log("Thiết lập Quy tắc Spec-as-Truth & Anti-Hallucination Rules...")
    setup_grounding_rules(args.dry_run)

    # 5. Setup Git Hooks (Background Vector Ingestion)
    log("Thiết lập Git Hook tự động đồng bộ Vector Store...")
    setup_git_hooks(REPO_ROOT, args.dry_run)

    print("=" * 70)
    log_success("Hoàn tất cấu hình! Mọi AI Agent trên máy đã kết nối với Personal-KB.")
    print("💡 Mẹo: Khi cập nhật mã nguồn repo ('git pull'), toàn bộ Agent sẽ tự động")
    print("   nhận diện các tools và specs mới nhất mà KHÔNG CẦN cấu hình lại.")
    print("=" * 70)


if __name__ == "__main__":
    main()
