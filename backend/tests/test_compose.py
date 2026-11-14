"""The personal-kb stack as docker-compose.yml declares it: services, local-only ports, healthchecks, mounts."""

import os
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DATABASES = ("postgres", "redis")


def mounts(service: dict) -> dict[str, tuple[str, bool]]:
    """target -> (source, read_only), from the short ("src:dst[:ro]") or long (dict) volume syntax."""
    found = {}
    for volume in service.get("volumes", []):
        if isinstance(volume, dict):
            source, target, read_only = volume["source"], volume["target"], bool(volume.get("read_only"))
        else:
            source, target, *mode = volume.split(":")
            read_only = "ro" in mode
        found[target] = (os.path.normpath(source), read_only)
    return found


@pytest.fixture(scope="module")
def stack():
    return yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))


def test_the_services_are_the_four_of_the_stack(stack):
    assert set(stack["services"]) == {"postgres", "redis", "backend", "frontend"}
    assert stack["name"] == "personal-kb"  # never shares a compose project with the CyberOS stack


def test_every_published_port_is_bound_to_localhost(stack):
    # redis has no password and DEV_LOGIN is on: nothing may listen on the LAN
    ports = {name: s.get("ports", []) for name, s in stack["services"].items()}

    assert all(ports.values()), ports
    assert [p for name in ports for p in ports[name] if not p.startswith("127.0.0.1:")] == []


def test_the_backend_starts_once_the_databases_are_healthy(stack):
    depends = stack["services"]["backend"]["depends_on"]

    assert {name: depends[name]["condition"] for name in DATABASES} == dict.fromkeys(DATABASES, "service_healthy")


def test_the_databases_have_a_healthcheck(stack):
    assert [name for name in DATABASES if "healthcheck" not in stack["services"][name]] == []


def test_the_data_lives_in_a_named_volume(stack):
    sources = [source for source, _ in mounts(stack["services"]["postgres"]).values()]

    assert "postgres_data" in sources and "postgres_data" in stack["volumes"]


def test_the_backend_reads_the_project_map_read_only(stack):
    backend = stack["services"]["backend"]

    assert mounts(backend)["/app/config"] == ("config", True)
    assert "PROJECTS_CONFIG=/app/config/projects.json" in backend["environment"]


def test_the_images_are_built_from_the_service_folders(stack):
    builds = {name: stack["services"][name]["build"] for name in ("backend", "frontend")}

    assert builds == {
        "backend": {"context": "./backend", "dockerfile": "Dockerfile"},
        "frontend": {**builds["frontend"], "context": "./frontend", "dockerfile": "Dockerfile.frontend"},
    }
    assert (REPO / "backend" / "Dockerfile").exists() and (REPO / "frontend" / "Dockerfile.frontend").exists()


def test_the_runtime_image_holds_every_tokenizer_the_code_loads():
    # the runtime user cannot write the tokenizer cache: an encoding not fetched at build time stops the app at import
    used = {
        name
        for path in (REPO / "backend" / "personal_kb").rglob("*.py")
        for name in re.findall(r"get_encoding\(\"(\w+)\"\)", path.read_text(encoding="utf-8"))
    }
    dockerfile = (REPO / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert used and all(f"'{name}'" in dockerfile for name in used), used


def test_the_backend_can_write_knowledge_for_web_approvals_and_uploads(stack):
    # /approvals and the upload page write specs from the container (Ryan, 2026-10-25: option a); the human gate is
    # the approval itself: MCP agents can only propose
    assert mounts(stack["services"]["backend"])["/app/knowledge"] == ("knowledge", False)


def test_mounts_reads_both_volume_syntaxes():
    # the tests compare what is mounted where, not how the line is written
    service = {"volumes": ["./config:/app/config:ro", {"type": "bind", "source": "knowledge", "target": "/app/kb"}]}

    assert mounts(service) == {"/app/config": ("config", True), "/app/kb": ("knowledge", False)}
