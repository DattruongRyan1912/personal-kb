import json
import logging
from types import SimpleNamespace

from tenacity import wait_none

from personal_kb.core.prompts import load_prompt
from personal_kb.services.query_entities import QueryEntityExtractor


class FakeChatAPI:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def create(self, **kwargs):  # like the SDK: a plain method returning a coroutine
        return self._create(**kwargs)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content, refusal=None))])


def extractor(api: FakeChatAPI) -> QueryEntityExtractor:
    client = SimpleNamespace(chat=SimpleNamespace(completions=api))
    return QueryEntityExtractor(client, model="gpt-4o-mini", prompt=load_prompt("query_entities"), wait=wait_none())


async def test_terms_are_normalized_deduplicated_and_short_ones_dropped():
    api = FakeChatAPI(json.dumps({"terms": ["Email", "notifications", "Registration", "email", "Gửi mail", "a"]}))

    terms = await extractor(api).terms("API gửi mail đăng ký ảnh hưởng đến bảng nào?")

    assert terms == ["email", "notifications", "registration", "gui_mail"]


async def test_the_query_is_sent_with_the_yaml_prompt_as_a_strict_structured_output():
    api = FakeChatAPI(json.dumps({"terms": ["login"]}))

    await extractor(api).terms("Luồng đăng nhập ghi bảng nào?")

    call = api.calls[0]
    assert call["response_format"]["json_schema"]["strict"] is True
    assert call["temperature"] == 0
    assert call["messages"][0]["content"] == load_prompt("query_entities").system
    assert "Luồng đăng nhập ghi bảng nào?" in call["messages"][1]["content"]


async def test_invalid_output_gives_no_terms_instead_of_an_error(caplog):
    caplog.set_level(logging.WARNING)

    assert await extractor(FakeChatAPI("not json")).terms("q") == []
    assert "QueryEntityExtractor" in caplog.text


async def test_reasoning_effort_reaches_the_request_when_configured():
    api = FakeChatAPI(json.dumps({"terms": ["login"]}))
    client = SimpleNamespace(chat=SimpleNamespace(completions=api))

    await QueryEntityExtractor(
        client, model="qwen3:8b", prompt=load_prompt("query_entities"), wait=wait_none(), reasoning_effort="none"
    ).terms("q")

    assert api.calls[0]["reasoning_effort"] == "none"
