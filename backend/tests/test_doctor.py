"""scripts/doctor.py: the checks that catch the silent drifts of 2026-10-25 (stdlib host script, fakes only)."""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("doctor", REPO / "scripts" / "doctor.py")
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)

OURS = {"command": "/bin/bash", "args": [str(REPO / "scripts" / "mcp_server.sh")], "env": {"PATH": "/usr/bin"}}
CYBEROS = {
    "command": "uv",
    "args": ["run", "--directory", "/Users/x/Project/CyberOS/ai/backend", "python", "-m", "cyberos_ai.mcp.cli"],
    "env": {"OPENAI_API_KEY": "sk-abcdefghijklmnopqrstuvwxyz123456"},
}


def test_the_mcp_entry_must_run_this_repo_server():
    assert doctor.check_mcp_entry({"mcpServers": {"personal-kb": OURS}}, REPO)[0] is True


def test_the_mcp_entry_running_via_uv_is_accepted():
    uv_ours = {
        "command": "uv",
        "args": [
            "run",
            "--directory",
            str(REPO / "backend"),
            "--env-file",
            str(REPO / ".env"),
            "python",
            "-m",
            "personal_kb.mcp.cli",
        ],
    }
    ok, verdict = doctor.check_mcp_entry({"mcpServers": {"personal-kb": uv_ours}}, REPO)
    assert ok is True
    assert "runs personal_kb.mcp.cli from this repo via uv" in verdict


def test_an_mcp_entry_pointing_elsewhere_names_the_directory_and_no_secret():
    ok, verdict = doctor.check_mcp_entry({"mcpServers": {"personal-kb": CYBEROS}}, REPO)

    assert ok is False
    assert "/Users/x/Project/CyberOS/ai/backend" in verdict
    assert "sk-" not in verdict and "OPENAI" not in verdict


def test_a_missing_mcp_entry_fails():
    assert doctor.check_mcp_entry({}, REPO)[0] is False


def test_an_empty_config_mount_says_how_to_fix_it():
    ok, verdict = doctor.check_project_map([])

    assert ok is False
    assert "docker compose up -d --force-recreate backend" in verdict
    assert doctor.check_project_map(["projects.json"])[0] is True


def test_config_mount_handles_failed_docker_process():
    import subprocess

    failed_proc = subprocess.CompletedProcess(
        args=["docker", "exec"],
        returncode=1,
        stdout="",
        stderr="Error response from daemon: container is not running",
    )
    ok, verdict = doctor.check_project_map(failed_proc)
    assert ok is False
    assert "kb-backend unreachable or offline" in verdict


def test_every_spec_on_disk_must_be_in_the_store():
    assert doctor.check_documents(27, 27)[0] is True
    ok, verdict = doctor.check_documents(25, 27)
    assert ok is False and "scripts/ingest.sh" in verdict


def test_a_spec_deleted_from_disk_but_still_in_the_store_fails():
    ok, verdict = doctor.check_documents(28, 27)

    assert ok is False and "not on disk" in verdict


def test_check_documents_set_reconciliation():
    # 1. Matching IDs 1:1
    ok, verdict = doctor.check_documents({"SPC-1", "SPC-2"}, {"SPC-1", "SPC-2"})
    assert ok is True
    assert "2 documents synchronized (IDs matched 1:1)" in verdict

    # 2. Spec on disk missing in database
    ok, verdict = doctor.check_documents({"SPC-1"}, {"SPC-1", "SPC-2"})
    assert ok is False
    assert "missing ['SPC-2']" in verdict
    assert "scripts/ingest.sh" in verdict

    # 3. Orphaned doc in database not on disk
    ok, verdict = doctor.check_documents({"SPC-1", "SPC-3"}, {"SPC-1"})
    assert ok is False
    assert "orphaned ['SPC-3']" in verdict

    # 4. Failed docker process
    import subprocess

    failed_proc = subprocess.CompletedProcess(
        args=["docker", "exec"],
        returncode=1,
        stdout="",
        stderr="Error response from daemon: container kb-postgres is not running",
    )
    ok, verdict = doctor.check_documents(failed_proc, {"SPC-1"})
    assert ok is False
    assert "kb-postgres unreachable or offline" in verdict


def test_the_report_can_be_json_for_scripts():
    report = doctor.render([("OK", "backend", "up"), ("WARN", "reranker", "down")], as_json=True)

    assert json.loads(report) == [
        {"level": "OK", "check": "backend", "verdict": "up"},
        {"level": "WARN", "check": "reranker", "verdict": "down"},
    ]
    assert doctor.render([("OK", "backend", "up")], as_json=False) == "OK   backend: up"


def test_the_reranker_down_is_a_warning_with_its_effect():
    level, verdict = doctor.reranker_level(None)

    assert level == "WARN" and "unranked" in verdict
    assert doctor.reranker_level([{"index": 0, "score": 0.9}])[0] == "OK"


def test_mcp_without_the_host_venv_is_a_warning_that_says_how_to_fix_it(tmp_path):
    level, verdict = doctor.mcp_runtime_level(tmp_path / "python")

    assert level == "WARN" and "docker exec" in verdict and "uv sync" in verdict
    (tmp_path / "python").write_text("")
    (tmp_path / "python").chmod(0o755)
    assert doctor.mcp_runtime_level(tmp_path / "python")[0] == "OK"


def test_the_report_exits_one_only_on_a_failure():
    assert doctor.exit_code([("OK", "a", ""), ("WARN", "b", "")]) == 0
    assert doctor.exit_code([("OK", "a", ""), ("FAIL", "b", "")]) == 1
