"""The one place an OpenAI client is built: the OpenAI API, or an OpenAI-compatible server (Ollama, LM Studio)."""

from openai import AsyncOpenAI

from personal_kb.core.config import Settings
from personal_kb.infrastructure.tracing import TracedOpenAI, Tracing


def build_openai_client(settings: Settings, tracing: Tracing | None = None) -> AsyncOpenAI | TracedOpenAI:
    # max_retries=0: services/openai_retry.py is the only retry layer
    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=settings.openai_base_url,
        max_retries=0,
        timeout=settings.openai_timeout_seconds,
    )
    # traced: each completion and embedding is a generation of the current trace (issue 4.1)
    return TracedOpenAI(client, tracing) if tracing is not None and tracing.enabled else client


def build_embedding_client(settings: Settings, tracing: Tracing | None = None) -> AsyncOpenAI | TracedOpenAI:
    if settings.embedding_base_url:
        api_key = (
            settings.embedding_api_key.get_secret_value()
            if settings.embedding_api_key
            else settings.openai_api_key.get_secret_value()
        )
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=settings.embedding_base_url,
            max_retries=0,
            timeout=settings.openai_timeout_seconds,
        )
        return TracedOpenAI(client, tracing) if tracing is not None and tracing.enabled else client
    return build_openai_client(settings, tracing)
