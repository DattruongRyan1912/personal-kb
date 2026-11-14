"""Langfuse tracing (issue 4.1): each chat turn is one trace, grouped with the other turns of its session.

The trace holds the agent chain as LangChain reports it through Langfuse's callback handler (Agent_Thinking, the
model calls with tokens, latency and model name, Tool_Executor and each tool with its arguments), plus the calls made
with the raw OpenAI client (spec selection, search terms, summaries, embeddings) through TracedOpenAI. Langfuse prices
the tokens per model, so each trace shows its cost.

Off without LANGFUSE_* keys. Langfuse never stands in a turn's way: it exports in the background, a client that cannot
start leaves tracing off, and anything it raises while a turn runs is logged and ignored (fire and forget).
"""

import logging
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from personal_kb.core.config import Settings
from personal_kb.core.masking import make_mask

log = logging.getLogger(__name__)


class _Recorder:
    """What a turn or a generation records once it is done; does nothing when tracing is off or Langfuse failed."""

    def __init__(self, observation: Any = None) -> None:
        self._observation = observation

    def _update(self, **fields: Any) -> None:
        if self._observation is None:
            return
        try:
            self._observation.update(**fields)
        except Exception:
            log.warning("[Tracing] could not record an observation", exc_info=True)

    def finish(self, answer: str) -> None:
        self._update(output=answer)

    def record(self, output: Any = None, usage: dict[str, int] | None = None) -> None:
        self._update(output=output, usage_details=usage)

    def fail(self, error: BaseException) -> None:
        # the type only: a message can quote a URL with its password, and Langfuse masks input and output, not this
        self._update(level="ERROR", status_message=type(error).__name__)


class Tracing:
    """Tracing off: no callbacks, turns and generations record nothing."""

    enabled = False

    def callbacks(self) -> list:
        return []

    @contextmanager
    def turn(self, *, user_id: str, session_id: str, question: str, tags: Sequence[str] = ()) -> Iterator[_Recorder]:
        yield _Recorder()

    @contextmanager
    def generation(
        self, *, name: str, model: str | None, input: Any, as_type: str = "generation"
    ) -> Iterator[_Recorder]:
        yield _Recorder()

    def shutdown(self) -> None:
        pass


class LangfuseTracing(Tracing):
    enabled = True

    def __init__(self, client: Any, public_key: str) -> None:
        self._client, self._public_key = client, public_key

    def callbacks(self) -> list:
        """A fresh handler for each turn; it finds our client through its public key."""
        try:
            from langfuse.langchain import CallbackHandler

            return [CallbackHandler(public_key=self._public_key)]
        except Exception:
            log.warning("[Tracing] no callback handler: this turn is not traced", exc_info=True)
            return []

    @contextmanager
    def turn(self, *, user_id: str, session_id: str, question: str, tags: Sequence[str] = ()) -> Iterator[_Recorder]:
        from langfuse import propagate_attributes

        with ExitStack() as stack:
            stack.enter_context(
                _guarded(
                    lambda: propagate_attributes(
                        user_id=user_id, session_id=session_id, tags=list(tags), trace_name="chat_turn"
                    )
                )
            )
            observation = stack.enter_context(
                _guarded(
                    lambda: self._client.start_as_current_observation(name="chat_turn", as_type="agent", input=question)
                )
            )
            yield _Recorder(observation)

    @contextmanager
    def generation(
        self, *, name: str, model: str | None, input: Any, as_type: str = "generation"
    ) -> Iterator[_Recorder]:
        opened = _guarded(
            lambda: self._client.start_as_current_observation(name=name, as_type=as_type, model=model, input=input)
        )
        with opened as observation:
            recorder = _Recorder(observation)
            try:
                yield recorder
            except Exception as error:
                recorder.fail(error)
                raise

    def shutdown(self) -> None:
        try:
            self._client.shutdown()
        except Exception:
            log.warning("[Tracing] Langfuse did not shut down cleanly", exc_info=True)


@contextmanager
def _guarded(open_context) -> Iterator[Any]:
    """Enters and exits a Langfuse context manager without ever letting it break the code it wraps."""
    try:
        context: AbstractContextManager = open_context()
        value = context.__enter__()
    except Exception:
        log.warning("[Tracing] Langfuse failed: this part is not traced", exc_info=True)
        yield None
        return
    try:
        yield value
    except BaseException as error:
        _exit(context, error)
        raise
    else:
        _exit(context, None)


def _exit(context: AbstractContextManager, error: BaseException | None) -> None:
    try:
        context.__exit__(type(error) if error else None, error, error.__traceback__ if error else None)
    except Exception:
        log.warning("[Tracing] Langfuse failed while closing an observation", exc_info=True)


def secrets_of(settings: Settings) -> list[str | None]:
    """This deployment's own secrets, masked wherever they appear in a trace."""

    def value(secret):
        return secret.get_secret_value() if secret else None

    return [
        value(settings.openai_api_key),
        value(settings.supabase_jwt_secret),
        value(settings.langfuse_secret_key),
        value(settings.postgres_url),  # the whole DSN: it holds the password
        settings.postgres_url and urlsplit(settings.postgres_url.get_secret_value()).password,  # and alone
    ]


def build_tracing(settings: Settings) -> Tracing:
    """Langfuse when both keys are set; a client that cannot start (bad URL, wrong version) leaves tracing off."""
    if not settings.tracing_enabled:
        return Tracing()
    secrets = secrets_of(settings)
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
            environment=settings.langfuse_environment,
            mask=make_mask(secrets),
        )
    except Exception:
        log.warning("[Tracing] Langfuse could not start: tracing off", exc_info=True)
        return Tracing()
    log.info("[Tracing] Langfuse on (%s)", settings.langfuse_base_url or "Langfuse Cloud")
    return LangfuseTracing(client, settings.langfuse_public_key)


class TracedOpenAI:
    """The raw OpenAI client, with every completion and embedding call recorded as a generation of the current trace.

    Not langfuse.openai: that patches the openai package for the whole process, so ChatOpenAI's calls, already traced
    by the callback handler, would be recorded twice. A completion is named after its structured output schema
    (spec_choice, query_terms, graph_extraction), else chat_completion.
    """

    def __init__(self, client: Any, tracing: Tracing) -> None:
        self._client, self._tracing = client, tracing
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._complete))
        self.embeddings = SimpleNamespace(create=self._embed)

    def __getattr__(self, name: str) -> Any:  # close() and everything else: the inner client's
        return getattr(self._client, name)

    async def _complete(self, **kwargs: Any) -> Any:
        schema = (kwargs.get("response_format") or {}).get("json_schema") or {}
        name = schema.get("name") or "chat_completion"
        with self._tracing.generation(name=name, model=kwargs.get("model"), input=kwargs.get("messages")) as gen:
            response = await self._client.chat.completions.create(**kwargs)
            usage = getattr(response, "usage", None)
            gen.record(
                output=response.choices[0].message.content if response.choices else None,
                usage={"input": usage.prompt_tokens, "output": usage.completion_tokens} if usage else None,
            )
            return response

    async def _embed(self, **kwargs: Any) -> Any:
        texts = kwargs.get("input")
        with self._tracing.generation(
            name="embedding", model=kwargs.get("model"), input=texts, as_type="embedding"
        ) as gen:
            response = await self._client.embeddings.create(**kwargs)
            usage = getattr(response, "usage", None)
            gen.record(output=f"{len(response.data)} vectors", usage={"input": usage.prompt_tokens} if usage else None)
            return response
