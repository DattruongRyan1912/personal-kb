from personal_kb.infrastructure.chat_model import build_chat_model, build_thorough_chat_model
from tests.conftest import make_settings


def test_the_agent_model_sends_reasoning_effort_only_when_set():
    assert build_chat_model(make_settings(llm_model="qwen3:8b", llm_reasoning_effort="none")).reasoning_effort == "none"
    assert build_chat_model(make_settings()).reasoning_effort is None


def test_no_thorough_model_unless_configured():
    assert build_thorough_chat_model(make_settings()) is None


def test_the_thorough_model_has_its_own_name_and_reasoning():
    settings = make_settings(llm_model="qwen3:8b", llm_reasoning_effort="none", llm_model_thorough="qwen3:14b")

    model = build_thorough_chat_model(settings)

    assert model.model_name == "qwen3:14b"
    assert model.reasoning_effort is None  # not sent: qwen3 thinks; the quick model's "none" does not carry over
    assert model.request_timeout == 600


def test_the_thorough_reasoning_effort_can_be_set_explicitly():
    settings = make_settings(llm_model_thorough="o4-mini", llm_reasoning_effort_thorough="high")

    assert build_thorough_chat_model(settings).reasoning_effort == "high"


def test_both_models_ask_for_token_usage_while_streaming():  # tokens and cost of streamed answers (4.1)
    # through another base URL (Ollama), ChatOpenAI does not ask for usage unless told to
    settings = make_settings(llm_model_thorough="qwen3:14b", openai_base_url="http://localhost:11434/v1")

    assert build_chat_model(settings).stream_usage is True
    assert build_thorough_chat_model(settings).stream_usage is True
