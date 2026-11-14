"""scripts/mcp_server.sh runs the MCP server on the host with the settings docker-compose.yml gives kb-backend."""

import subprocess
from pathlib import Path

import yaml

from personal_kb.core.config import Settings

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "scripts" / "mcp_server.sh"
API_ONLY = {"PORT", "CORS_ORIGINS", "DEV_LOGIN"}  # the HTTP server's settings, not the MCP server's


def launch(tmp_path: Path, *env_lines: str) -> tuple[dict[str, str], str, subprocess.CompletedProcess]:
    """Run the launcher against a stub python; return the environment and arguments the server would start with."""
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(env_lines) + "\n")
    stub = tmp_path / "python"
    stub.write_text(f'#!/bin/sh\nprintf "%s" "$*" > "{tmp_path}/args"\nenv > "{tmp_path}/env"\n')
    stub.chmod(0o755)
    done = subprocess.run(
        ["/bin/bash", str(LAUNCHER)],
        env={"PATH": "/usr/bin:/bin", "KB_ENV_FILE": str(env_file), "KB_MCP_PYTHON": str(stub)},
        capture_output=True,
        timeout=10,
        check=True,
    )
    env = dict(line.split("=", 1) for line in (tmp_path / "env").read_text().splitlines() if "=" in line)
    return env, (tmp_path / "args").read_text(), done


def compose_backend_keys() -> set[str]:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    return {item.split("=", 1)[0] for item in compose["services"]["backend"]["environment"]}


def test_the_server_gets_every_setting_compose_gives_the_backend(tmp_path):
    env, _, _ = launch(tmp_path, "OPENAI_API_KEY=test")

    assert compose_backend_keys() - API_ONLY - env.keys() == set()


def test_services_are_reached_on_their_host_ports(tmp_path):
    env, args, done = launch(
        tmp_path,
        "OPENAI_API_KEY=test",
        "PG_USER=u",
        "PG_PASSWORD=p",
        "PG_DATABASE=db",
        "PG_PORT=5999",
        "REDIS_PORT=6999",
        "EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1",
    )

    assert env["POSTGRES_URL"] == "postgresql://u:p@127.0.0.1:5999/db"
    assert env["REDIS_URL"] == "redis://127.0.0.1:6999/0"
    assert env["EMBEDDING_BASE_URL"] == "http://127.0.0.1:11434/v1"
    assert env["RERANKER_URL"] == "http://127.0.0.1:8081"
    assert env["PROJECTS_CONFIG"] == str(REPO / "config" / "projects.json")
    assert args == "-m personal_kb.mcp.cli"
    assert done.stdout == b""  # stdout is the JSON-RPC channel


def test_defaults_that_differ_from_the_settings_class_follow_compose(tmp_path):
    env, _, _ = launch(tmp_path, "OPENAI_API_KEY=test")

    assert env["POSTGRES_SCHEMA"] == "public"  # Settings: memory
    assert env["EMBEDDING_DIMENSIONS"] == "1024"  # Settings: 1536, chunks.embedding is vector(1024)
    assert env["GRAPH_SEARCH"] == "false"  # Settings: true


def test_the_settings_load_from_that_environment(tmp_path, monkeypatch):
    env, _, _ = launch(tmp_path, "OPENAI_API_KEY=test")
    for key in [k for k in Settings.model_fields if k.upper() not in env]:
        monkeypatch.delenv(key.upper(), raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)

    assert settings.postgres_schema == "public" and settings.embedding_dimensions == 1024
