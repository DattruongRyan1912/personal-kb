import pytest
from pydantic import ValidationError

from personal_kb.core.config import Settings


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Run in an empty directory with no settings in the process environment."""
    monkeypatch.chdir(tmp_path)
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    return tmp_path


def required_env(monkeypatch, **overrides):
    values = {
        "OPENAI_API_KEY": "sk-test",
        "POSTGRES_URL": "postgresql://kb:pg-pass@postgres:5432/kb",
        "RERANKER_URL": "http://reranker:80",
        "SUPABASE_URL": "https://project.supabase.co",
        "REDIS_URL": "redis://redis:6379/0",
    } | overrides
    for name, value in values.items():
        if value is not None:
            monkeypatch.setenv(name, value)


def test_settings_load_required_values_from_env(clean_env, monkeypatch):
    required_env(monkeypatch)

    s = Settings()

    assert s.openai_api_key.get_secret_value() == "sk-test"
    assert s.embedding_model == "text-embedding-3-small"
    assert s.embedding_dimensions == 1536
    assert s.postgres_url.get_secret_value() == "postgresql://kb:pg-pass@postgres:5432/kb"
    assert s.postgres_schema == "memory"
    assert s.llm_model == "gpt-4o-mini"
    assert s.reranker_url == "http://reranker:80"
    assert s.openai_base_url is None  # the OpenAI API itself
    assert s.supabase_url == "https://project.supabase.co"
    assert s.supabase_jwt_secret is None  # projects on asymmetric signing keys need no secret
    assert s.llm_reasoning_effort is None  # not sent: gpt-4o-mini refuses it


def test_missing_supabase_url_is_refused(clean_env, monkeypatch):
    required_env(monkeypatch, SUPABASE_URL=None)

    with pytest.raises(ValidationError, match="supabase_url"):
        Settings()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("http://host.docker.internal:11434/v1", "http://host.docker.internal:11434/v1"), ("", None)],
)
def test_openai_base_url_points_at_a_compatible_server_or_is_empty(clean_env, monkeypatch, value, expected):
    required_env(monkeypatch, OPENAI_BASE_URL=value)

    assert Settings().openai_base_url == expected


def test_missing_postgres_url_is_refused(clean_env, monkeypatch):
    required_env(monkeypatch, POSTGRES_URL=None)

    with pytest.raises(ValidationError, match="postgres_url"):
        Settings()


def test_missing_openai_key_is_refused(clean_env, monkeypatch):
    required_env(monkeypatch, OPENAI_API_KEY=None)

    with pytest.raises(ValidationError, match="openai_api_key"):
        Settings()


def test_misspelled_key_in_env_file_is_refused(clean_env):
    (clean_env / ".env").write_text(
        "OPENAI_API_KEYY=sk-test\nPOSTGRES_URL=postgresql://u:p@pg:5432/kb\n"
        "RERANKER_URL=http://reranker:80\nSUPABASE_URL=https://p.supabase.co\nREDIS_URL=redis://r:6379/0\n"
    )

    with pytest.raises(ValidationError, match="openai_api_key"):
        Settings()


def test_empty_openai_key_is_refused(clean_env, monkeypatch):
    required_env(monkeypatch, OPENAI_API_KEY="")

    with pytest.raises(ValidationError, match="openai_api_key"):
        Settings()


def test_validation_error_does_not_print_the_api_key(clean_env, monkeypatch):
    required_env(monkeypatch, OPENAI_API_KEY="sk-secret-value", REDIS_URL=None)

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert "redis_url" in str(excinfo.value)
    assert "sk-secret-value" not in str(excinfo.value)


def test_the_agents_tool_call_limit_defaults_to_twelve_and_stays_bounded(clean_env, monkeypatch):
    required_env(monkeypatch)
    assert Settings().agent_max_tool_calls == 12  # the specs read included

    monkeypatch.setenv("AGENT_MAX_TOOL_CALLS", "50")
    assert Settings().agent_max_tool_calls == 50
    for bad in ("0", "51"):
        monkeypatch.setenv("AGENT_MAX_TOOL_CALLS", bad)
        with pytest.raises(ValidationError):
            Settings()


def test_the_thorough_model_is_optional_and_an_empty_value_means_unset(clean_env, monkeypatch):
    required_env(monkeypatch, LLM_MODEL_THOROUGH="", LLM_REASONING_EFFORT_THOROUGH="")
    s = Settings()
    assert s.llm_model_thorough is None and s.llm_reasoning_effort_thorough is None


def test_the_postgres_url_never_shows_in_the_settings_repr():
    from tests.conftest import make_settings

    settings = make_settings(postgres_url="postgresql://u:s3cret-pass@h/db")

    assert "s3cret-pass" not in repr(settings)


def test_a_schema_name_that_is_not_an_identifier_is_refused():
    from tests.conftest import make_settings

    with pytest.raises(ValidationError, match="should match pattern"):
        make_settings(postgres_schema="memory; drop")


def test_embedding_base_url_and_api_key_are_optional(clean_env, monkeypatch):
    required_env(monkeypatch, EMBEDDING_BASE_URL="http://ollama:11434/v1", EMBEDDING_API_KEY="sk-embed")
    s = Settings()
    assert s.embedding_base_url == "http://ollama:11434/v1"
    assert s.embedding_api_key.get_secret_value() == "sk-embed"
