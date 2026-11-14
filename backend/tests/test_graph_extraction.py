import json
import logging
from types import SimpleNamespace

import httpx2
import openai
import pytest
from tenacity import wait_none

from personal_kb.core.prompts import PROMPTS_DIR, load_prompt
from personal_kb.services.chunking import SpecChunk
from personal_kb.services.graph_extraction import GraphExtractor

CHUNK = SpecChunk(
    spec_id="SPC-1",
    headings=["# 2. API", "## 2.1 POST /api/v1/auth/login"],
    content="Login writes users.last_login_at.",
    chunk_index=3,
)

VALID = {
    "nodes": [
        {"id": "spec:spc_1", "label": "Spec"},
        {"id": "feature:login", "label": "Feature"},
        {"id": "db_table:Users", "label": "Database_Table"},
    ],
    "edges": [
        {"source_id": "spec:spc_1", "target_id": "feature:login", "relation_type": "DEFINES"},
        {"source_id": "feature:login", "target_id": "db_table:users", "relation_type": "MODIFIES"},
    ],
}


class FakeChatAPI:
    """Stands in for `AsyncOpenAI().chat.completions`: fails with the queued errors, then answers `content`."""

    def __init__(self, content: str, errors=(), refusal: str | None = None):
        self.content, self.errors, self.refusal = content, list(errors), refusal
        self.calls = []

    def create(self, **kwargs):
        # like the real SDK: a plain method that returns a coroutine, not an `async def`
        return self._create(**kwargs)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        message = SimpleNamespace(content=self.content, refusal=self.refusal)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def extractor(api: FakeChatAPI) -> GraphExtractor:
    client = SimpleNamespace(chat=SimpleNamespace(completions=api))
    return GraphExtractor(client, model="gpt-4o-mini", prompt=load_prompt("graph_extraction"), wait=wait_none())


def test_the_prompt_lives_in_a_yaml_file():
    prompt = load_prompt("graph_extraction")

    assert (PROMPTS_DIR / "graph_extraction.yaml").is_file()
    assert "Database_Table" in prompt.system and "MODIFIES" in prompt.system
    assert "db_table:users" in prompt.system


def test_rendering_a_prompt_needs_every_variable():
    with pytest.raises(KeyError):
        load_prompt("graph_extraction").render_user(spec_id="SPC-1")


async def test_valid_output_becomes_a_normalized_graph():
    api = FakeChatAPI(json.dumps(VALID))

    graph = await extractor(api).extract(CHUNK)

    assert [n.id for n in graph.nodes] == ["spec:spc_1", "feature:login", "db_table:users"]
    assert [(e.source_id, e.relation_type, e.target_id) for e in graph.edges][1] == (
        "feature:login",
        "MODIFIES",
        "db_table:users",
    )


async def test_request_uses_strict_structured_output_and_the_yaml_prompt():
    api = FakeChatAPI(json.dumps(VALID))

    await extractor(api).extract(CHUNK)

    call = api.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["temperature"] == 0
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True
    system, user = call["messages"]
    assert system == {"role": "system", "content": load_prompt("graph_extraction").system}
    assert "spec:spc_1" in user["content"]
    assert "## 2.1 POST /api/v1/auth/login" in user["content"]
    assert CHUNK.content in user["content"]


@pytest.mark.parametrize(
    "content",
    [
        "Sure! Here is the graph: {",  # not JSON
        json.dumps({"nodes": [{"id": "x:y", "label": "Service"}], "edges": []}),  # outside the ontology
        json.dumps({"nodes": [], "edges": [VALID["edges"][1]]}),  # dangling edge
    ],
)
async def test_invalid_output_skips_the_chunk_with_a_warning(content, caplog):
    caplog.set_level(logging.WARNING)

    assert await extractor(FakeChatAPI(content)).extract(CHUNK) is None
    assert "SPC-1" in caplog.text and "skipped" in caplog.text


async def test_a_refusal_skips_the_chunk(caplog):
    caplog.set_level(logging.WARNING)

    assert await extractor(FakeChatAPI("", refusal="I can't help with that")).extract(CHUNK) is None
    assert "refused" in caplog.text


async def test_rate_limit_is_retried():
    request = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = openai.RateLimitError("slow down", response=httpx2.Response(429, request=request), body=None)
    api = FakeChatAPI(json.dumps(VALID), errors=[error])

    assert await extractor(api).extract(CHUNK) is not None
    assert len(api.calls) == 2


async def test_reasoning_effort_is_sent_only_when_configured():
    plain, local = FakeChatAPI(json.dumps(VALID)), FakeChatAPI(json.dumps(VALID))
    client = SimpleNamespace(chat=SimpleNamespace(completions=local))
    prompt = load_prompt("graph_extraction")

    await extractor(plain).extract(CHUNK)
    await GraphExtractor(client, model="qwen3:8b", prompt=prompt, wait=wait_none(), reasoning_effort="none").extract(
        CHUNK
    )

    assert "reasoning_effort" not in plain.calls[0]  # gpt-4o-mini refuses the parameter
    assert local.calls[0]["reasoning_effort"] == "none"  # Ollama: no thinking, several times faster


async def test_a_chunk_still_timing_out_after_the_retries_raises_so_the_revision_is_not_applied():
    # skipping it would let the revision retract the chunk it replaced (PoC-A, final review)
    request = httpx2.Request("POST", "http://localhost:11434/v1/chat/completions")
    api = FakeChatAPI(json.dumps(VALID), errors=[openai.APITimeoutError(request=request) for _ in range(6)])

    with pytest.raises(openai.APITimeoutError):
        await extractor(api).extract(CHUNK)
    assert len(api.calls) == 6


async def test_a_model_without_structured_output_stops_the_run_at_once():
    request = httpx2.Request("POST", "http://localhost:11434/v1/chat/completions")
    error = openai.InternalServerError("not implemented", response=httpx2.Response(501, request=request), body=None)
    api = FakeChatAPI(json.dumps(VALID), errors=[error])

    with pytest.raises(openai.InternalServerError):
        await extractor(api).extract(CHUNK)
    assert len(api.calls) == 1


async def test_a_wrong_api_key_still_stops_the_run():
    request = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = openai.AuthenticationError("bad key", response=httpx2.Response(401, request=request), body=None)

    with pytest.raises(openai.AuthenticationError):
        await extractor(FakeChatAPI(json.dumps(VALID), errors=[error])).extract(CHUNK)
