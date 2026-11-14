"""Application settings, loaded once from the environment (and `.env` when run outside Docker).

Fail-fast: a missing, empty or misspelled required variable raises a pydantic ValidationError at startup,
so the server refuses to start instead of failing on the first request (issue 1.1).
"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class Settings(BaseSettings):
    # hide_input_in_errors: a validation error must never print a secret it was given into the logs
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="forbid", hide_input_in_errors=True
    )

    openai_api_key: SecretStr = Field(min_length=1)
    reranker_url: str = Field(min_length=1)
    redis_url: str = Field(min_length=1)  # chat working memory (issue 2.1)
    supabase_url: str = Field(min_length=1)  # e.g. https://<project>.supabase.co; tokens are issued by <url>/auth/v1

    # project name -> repo path and git author; the worklog accepts only these project names
    projects_config: Path = Path("../config/projects.json")

    # search also asks the LLM for the question's terms and reads the knowledge graph; off when no graph is ingested
    graph_search: bool = True

    # unset or empty: the OpenAI API; otherwise an OpenAI-compatible server such as Ollama or LM Studio
    openai_base_url: str | None = None
    # separate base URL and API key for embeddings when LLM uses a completion-only provider (e.g. DeepSeek)
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    # only for projects still signing with the legacy JWT secret (HS256); asymmetric keys come from the JWKS endpoint
    supabase_jwt_secret: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"
    # sent only when set: "none" turns thinking off on Ollama (qwen3: ~0.7 s instead of ~3 s); gpt-4o-mini refuses it
    llm_reasoning_effort: str | None = None
    # one call to the model or embedding server gives up after this (the SDK default is 10 minutes); the retry policy
    # then tries again, so a hung server cannot hold a search or an ingestion for long
    openai_timeout_seconds: float = Field(default=60, gt=0)
    # the model that answers once the specs are read; unset: llm_model. Measured on six hard questions: qwen3:14b
    # with thinking 75%, qwen3:8b without 48% (ai/evidence/judge-experiment)
    llm_model_thorough: str | None = None
    # sent with llm_model_thorough only when set; unset lets qwen3 think, and suits models that refuse the field
    llm_reasoning_effort_thorough: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    # tool calls per question, the catalog and the specs read included (12 proposed on #268; the 5 agreed on #266,
    # point 7, was for an agent that only searched); at most 50, a backstop for loops
    agent_max_tool_calls: int = Field(default=12, ge=1, le=50)
    # when False: pure chunk-based RAG (does not read whole specs into prompt, saving 90%+ tokens on large docs)
    agent_read_specs: bool = True
    # origins of the chat UI allowed to call the API from a browser, comma-separated (issue 3.2)
    cors_origins: str = ""
    # Base URL for frontend web app, used for clickable citation deep links in MCP and agent answers
    frontend_base_url: str = "http://localhost:3000"
    # Agent M2M API authentication key (optional)
    agent_api_key: SecretStr | None = None
    # POST /api/v1/dev/token signs in a dev user without Supabase: only against a local Supabase URL and JWT secret
    dev_login: bool = False
    # Langfuse tracing (issue 4.1), on when both keys are set; base URL unset: Langfuse Cloud (EU)
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str | None = None
    langfuse_environment: str | None = None  # e.g. development, production: traces are filtered by it
    # where the long-term memory lives (decision B4): one Postgres with pgvector
    postgres_url: SecretStr = Field(min_length=1)  # postgresql://user:password@host:port/db; carries a password
    postgres_pool_size: int = Field(default=10, ge=1)
    # the schema the memory tables live in; formatted into SQL, so only a plain identifier is accepted
    postgres_schema: str = Field(default="memory", pattern=r"^[a-z_][a-z0-9_]*$")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _dev_login_only_locally(self):
        if self.dev_login and (
            self.supabase_jwt_secret is None or urlparse(self.supabase_url).hostname not in _LOCAL_HOSTS
        ):
            raise ValueError("DEV_LOGIN needs a local SUPABASE_URL (localhost) and SUPABASE_JWT_SECRET")
        return self

    @model_validator(mode="after")
    def _langfuse_keys_come_together(self):
        if (self.langfuse_public_key is None) != (self.langfuse_secret_key is None):
            raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set together, or neither")
        return self

    @property
    def tracing_enabled(self) -> bool:
        return self.langfuse_public_key is not None and self.langfuse_secret_key is not None

    @field_validator(
        "openai_base_url",
        "supabase_jwt_secret",
        "llm_reasoning_effort",
        "llm_model_thorough",
        "llm_reasoning_effort_thorough",
        "langfuse_public_key",
        "langfuse_secret_key",
        "langfuse_base_url",
        "langfuse_environment",
        mode="before",
    )
    @classmethod
    def _empty_means_unset(cls, value):
        return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
