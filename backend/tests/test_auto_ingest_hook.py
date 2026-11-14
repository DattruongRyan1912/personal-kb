"""Unit tests for background auto-ingestion hook and setup."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_setup_git_hooks_creates_post_commit_hook(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("setup_agent", REPO_ROOT / "scripts" / "setup_agent.py")
    setup_agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup_agent)

    fake_git = tmp_path / ".git"
    fake_git.mkdir()

    # Dry run should not write file
    setup_agent.setup_git_hooks(tmp_path, dry_run=True)
    assert not (fake_git / "hooks" / "post-commit").exists()

    # Real run should create executable hook
    setup_agent.setup_git_hooks(tmp_path, dry_run=False)
    hook_file = fake_git / "hooks" / "post-commit"
    assert hook_file.is_file()
    assert "auto_ingest_hook.sh" in hook_file.read_text()
    import os

    assert os.access(hook_file, os.X_OK)


def test_auto_ingest_hook_script_exists_and_is_executable():
    hook_script = REPO_ROOT / "scripts" / "auto_ingest_hook.sh"
    assert hook_script.is_file()
    import os

    assert os.access(hook_script, os.X_OK)


def test_auto_ingest_hook_runs_cleanly_on_current_repo():
    hook_script = REPO_ROOT / "scripts" / "auto_ingest_hook.sh"
    res = subprocess.run([str(hook_script)], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
