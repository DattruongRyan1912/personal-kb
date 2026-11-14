"""The LangChain chat model of the agent: the OpenAI API, or an OpenAI-compatible server (Ollama, LM Studio)."""

from langchain_openai import ChatOpenAI

from personal_kb.core.config import Settings

THOROUGH_TIMEOUT_SECONDS = 600  # a thinking model may reason for minutes before its first word


def build_chat_model(settings: Settings) -> ChatOpenAI:
    options: dict = {
        "model": settings.llm_model,
        "api_key": settings.openai_api_key.get_secret_value(),
        "base_url": settings.openai_base_url,
        "temperature": 0,
        "max_retries": 2,
        "stream_usage": True,  # through another base URL (Ollama) usage is only streamed when asked: tokens, cost (4.1)
    }
    if settings.llm_reasoning_effort:  # "none" turns qwen3's thinking off on Ollama; gpt-4o-mini refuses the field
        options["reasoning_effort"] = settings.llm_reasoning_effort
    return ChatOpenAI(**options)


def build_thorough_chat_model(settings: Settings) -> ChatOpenAI | None:
    """The model that answers once the specs are read, when one is configured (LLM_MODEL_THOROUGH)."""
    if not settings.llm_model_thorough:
        return None
    options: dict = {
        "model": settings.llm_model_thorough,
        "api_key": settings.openai_api_key.get_secret_value(),
        "base_url": settings.openai_base_url,
        "temperature": 0,
        "max_retries": 2,
        "timeout": THOROUGH_TIMEOUT_SECONDS,
        "stream_usage": True,
    }
    if settings.llm_reasoning_effort_thorough:
        options["reasoning_effort"] = settings.llm_reasoning_effort_thorough
    return ChatOpenAI(**options)
