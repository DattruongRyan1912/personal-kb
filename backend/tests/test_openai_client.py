from personal_kb.infrastructure.openai_client import build_openai_client
from tests.conftest import make_settings


def settings(**kw):
    return make_settings(openai_api_key="ollama", **kw)


def test_the_client_targets_openai_by_default_and_never_retries_on_its_own():
    client = build_openai_client(settings())

    assert str(client.base_url).startswith("https://api.openai.com")
    assert client.max_retries == 0  # openai_retry is the only retry layer


def test_the_client_targets_a_compatible_server_when_a_base_url_is_set():
    client = build_openai_client(settings(openai_base_url="http://host.docker.internal:11434/v1"))

    assert str(client.base_url).rstrip("/") == "http://host.docker.internal:11434/v1"


def test_a_call_gives_up_after_the_configured_timeout_not_the_sdk_default_of_ten_minutes():
    assert build_openai_client(settings()).timeout == 60
    assert build_openai_client(settings(openai_timeout_seconds=15)).timeout == 15


def test_embedding_client_uses_separate_base_url_when_configured():
    from personal_kb.infrastructure.openai_client import build_embedding_client

    client = build_embedding_client(
        settings(
            openai_base_url="https://api.deepseek.com/v1",
            embedding_base_url="http://host.docker.internal:11434/v1",
        )
    )
    assert str(client.base_url).rstrip("/") == "http://host.docker.internal:11434/v1"
