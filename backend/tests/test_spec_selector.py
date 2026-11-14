import json

from tenacity import wait_none

from personal_kb.core.prompts import load_prompt
from personal_kb.services.spec_selector import SpecSelector
from tests.test_query_entities import FakeChatAPI

CATALOG = "- SPC-1: Luồng đăng nhập\n- SPC-2: Luồng thanh toán đơn hàng\n- SPC-3: Đăng ký tài khoản"


def selector(api: FakeChatAPI) -> SpecSelector:
    from types import SimpleNamespace

    client = SimpleNamespace(chat=SimpleNamespace(completions=api))
    return SpecSelector(client, model="qwen3:8b", prompt=load_prompt("spec_selection"), wait=wait_none())


async def test_the_chosen_ids_are_kept_in_order_without_repeats_and_within_the_limit():
    api = FakeChatAPI(json.dumps({"spec_ids": ["SPC-3", "SPC-1", "SPC-3", "SPC-2"]}))

    assert await selector(api).select("Đăng ký rồi đăng nhập", CATALOG, limit=2) == ["SPC-3", "SPC-1"]


async def test_the_question_catalog_and_limit_reach_the_model_as_a_strict_structured_output():
    api = FakeChatAPI(json.dumps({"spec_ids": []}))

    await selector(api).select("Kịch bản thanh toán", CATALOG, limit=4)

    sent = api.calls[0]
    assert sent["response_format"]["json_schema"]["strict"] is True
    user = sent["messages"][-1]["content"]
    assert "Kịch bản thanh toán" in user and "SPC-2: Luồng thanh toán đơn hàng" in user and "4" in user


async def test_a_bad_answer_selects_nothing():
    assert await selector(FakeChatAPI("not json")).select("q", CATALOG, limit=4) == []


async def test_selector_falls_back_to_json_object_when_json_schema_unavailable():
    import httpx
    import openai

    class FallbackFakeChatAPI:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["response_format"].get("type") == "json_schema":
                raise openai.BadRequestError(
                    message="This response_format type is unavailable now",
                    response=httpx.Response(400, request=httpx.Request("POST", "http://test")),
                    body={"error": {"message": "unavailable"}},
                )
            from types import SimpleNamespace

            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=json.dumps({"spec_ids": ["SPC-2"]}), refusal=None))
                ]
            )

    api = FallbackFakeChatAPI()
    result = await selector(api).select("Kịch bản thanh toán", CATALOG, limit=2)
    assert result == ["SPC-2"]
    assert len(api.calls) == 2
    assert api.calls[0]["response_format"]["type"] == "json_schema"
    assert api.calls[1]["response_format"]["type"] == "json_object"
