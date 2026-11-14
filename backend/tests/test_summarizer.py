from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from tenacity import wait_none

from personal_kb.core.prompts import load_prompt
from personal_kb.services.summarizer import LlmSummarizer


class FakeChatAPI:
    def __init__(self, answer="Người dùng hỏi về luồng thanh toán SPC-2."):
        self.answer, self.calls = answer, []

    def create(self, **kwargs):  # like the SDK: a plain method returning a coroutine
        return self._create(**kwargs)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.answer))])


def summarizer(api, **kw):
    client = SimpleNamespace(chat=SimpleNamespace(completions=api))
    return LlmSummarizer(client, model="gpt-4o-mini", prompt=load_prompt("session_summary"), wait=wait_none(), **kw)


async def test_the_summary_is_the_models_answer_to_the_yaml_prompt():
    api = FakeChatAPI()

    text = await summarizer(api).summarize(None, [HumanMessage("Tìm luồng thanh toán"), AIMessage("Xem SPC-2")])

    assert text == "Người dùng hỏi về luồng thanh toán SPC-2."
    call = api.calls[0]
    assert call["model"] == "gpt-4o-mini" and call["temperature"] == 0
    assert call["messages"][0] == {"role": "system", "content": load_prompt("session_summary").system}
    assert "user: Tìm luồng thanh toán" in call["messages"][1]["content"]


async def test_the_assistants_answers_reach_the_summary_only_as_the_specs_they_cite():
    api = FakeChatAPI()
    wrong = AIMessage("Lần 6 trả 200 OK, bộ đếm về 0 [Luồng đăng nhập](SPC-1).")

    await summarizer(api).summarize(None, [HumanMessage("Lần 6 thì sao?"), wrong, AIMessage("Chào bạn!")])

    transcript = api.calls[0]["messages"][1]["content"]
    assert "200 OK" not in transcript and "bộ đếm" not in transcript  # a wrong answer cannot be summarized as fact
    assert "assistant answered, citing [Luồng đăng nhập](SPC-1)" in transcript
    assert "assistant answered, citing no spec" in transcript


async def test_the_previous_summary_and_the_specs_tools_named_are_part_of_the_input():
    api = FakeChatAPI()
    tool_call = AIMessage("", tool_calls=[{"id": "c1", "name": "get_full_spec_content", "args": {"spec_id": "SPC-2"}}])

    read = ToolMessage("SPC-2 — Luồng thanh toán đơn hàng\n\nbảng payments", tool_call_id="c1")
    await summarizer(api).summarize("Trước đó: hỏi về đăng nhập.", [tool_call, read])

    transcript = api.calls[0]["messages"][1]["content"]
    assert "Trước đó: hỏi về đăng nhập." in transcript
    assert 'assistant called get_full_spec_content({"spec_id": "SPC-2"})' in transcript
    assert "tool result naming SPC-2 «Luồng thanh toán đơn hàng»" in transcript
    assert "bảng payments" not in transcript  # spec content is read again when needed, never summarized


async def test_reasoning_effort_is_sent_only_when_configured():
    plain, local = FakeChatAPI(), FakeChatAPI()

    await summarizer(plain).summarize(None, [HumanMessage("a")])
    await summarizer(local, reasoning_effort="none").summarize(None, [HumanMessage("a")])

    assert "reasoning_effort" not in plain.calls[0] and local.calls[0]["reasoning_effort"] == "none"


def test_the_summary_keeps_what_was_asked_not_the_assistants_conclusions():
    from personal_kb.core.prompts import load_prompt

    system = load_prompt("session_summary").system
    assert "Do not record the assistant's technical answers" in system
