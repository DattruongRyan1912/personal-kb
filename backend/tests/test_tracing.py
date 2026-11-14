import time
from contextlib import contextmanager
from types import SimpleNamespace

import fakeredis
import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from personal_kb.infrastructure.tracing import TracedOpenAI, Tracing, build_tracing
from personal_kb.services.agent import ChatAgent
from personal_kb.services.session_memory import SessionMemoryManager
from personal_kb.tools.base import ToolContext
from personal_kb.tools.registry import ToolRegistry
from tests.conftest import make_settings
from tests.test_agent import FakeSpecTool, ScriptedModel, call
from tests.test_agent_stream import StreamingModel

KEYS = {"langfuse_public_key": "pk-lf-test", "langfuse_secret_key": "sk-lf-test"}


class RecordingHandler(BaseCallbackHandler):
    def __init__(self):
        self.llm_starts, self.tools = 0, []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.llm_starts += 1

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.tools.append(input_str)


class RecordingTracing(Tracing):
    enabled = True

    def __init__(self):
        self.handler, self.turns, self.generations = RecordingHandler(), [], []

    def callbacks(self):
        return [self.handler]

    @contextmanager
    def turn(self, *, user_id, session_id, question, tags=()):
        record = {"user": user_id, "session": session_id, "question": question, "tags": list(tags), "answer": None}
        self.turns.append(record)
        yield SimpleNamespace(finish=lambda answer: record.update(answer=answer))

    @contextmanager
    def generation(self, *, name, model, input, as_type="generation"):
        record = {"name": name, "model": model, "as_type": as_type, "usage": None, "error": None}
        self.generations.append(record)
        try:
            yield SimpleNamespace(record=lambda output=None, usage=None: record.update(usage=usage))
        except Exception as exc:
            record["error"] = repr(exc)
            raise


def agent_with(script, tracing=None, model_class=ScriptedModel):
    memory = SessionMemoryManager(fakeredis.FakeAsyncRedis(), summarizer=None, threshold_tokens=100_000)
    return ChatAgent(
        model=model_class(script=script),
        tools=ToolRegistry([FakeSpecTool()]),
        memory=memory,
        persona="p",
        tracing=tracing,
    )


def tool_then_answer():
    return [AIMessage("", tool_calls=[call("SPC-1", "c1")]), AIMessage("Đáp án.")]


def test_tracing_is_off_without_keys():
    tracing = build_tracing(make_settings())

    assert not tracing.enabled and tracing.callbacks() == []


@pytest.mark.parametrize("only", ["langfuse_public_key", "langfuse_secret_key"])
def test_one_langfuse_key_without_the_other_is_refused(only):
    with pytest.raises(ValidationError):
        make_settings(**{only: KEYS[only]})


def test_a_langfuse_that_cannot_start_turns_tracing_off(monkeypatch, caplog):
    import langfuse

    def broken(**kwargs):
        raise RuntimeError("bad host")

    monkeypatch.setattr(langfuse, "Langfuse", broken)

    tracing = build_tracing(make_settings(**KEYS))

    assert not tracing.enabled and "tracing off" in caplog.text


async def test_a_traced_turn_passes_the_callbacks_and_records_question_and_answer():
    tracing = RecordingTracing()
    agent = agent_with(tool_then_answer(), tracing)

    answer = await agent.ask("u1", "s1", "SPC-1 băm mật khẩu bằng gì?", ToolContext(None, None))

    assert tracing.handler.llm_starts == 2 and "SPC-1" in tracing.handler.tools[0]
    assert tracing.turns == [
        {"user": "u1", "session": "s1", "question": "SPC-1 băm mật khẩu bằng gì?", "tags": [], "answer": answer.content}
    ]


async def test_tracing_leaves_the_stream_unchanged():
    async def events(tracing):
        agent = agent_with(tool_then_answer(), tracing, model_class=StreamingModel)
        return [e async for e in agent.stream("u", "s", "q", ToolContext(None, None))]

    traced, plain = await events(RecordingTracing()), await events(None)

    assert traced == plain and traced[-1] == {"type": "done"}


async def test_traced_openai_records_each_completion_and_embedding_and_lets_errors_through():
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18)

    class Completions:
        async def create(self, **kwargs):
            if kwargs.get("model") == "broken":
                raise TimeoutError("upstream")
            return SimpleNamespace(usage=usage, choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    class Embeddings:
        async def create(self, **kwargs):
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=5, total_tokens=5), data=[1, 2])

    inner = SimpleNamespace(chat=SimpleNamespace(completions=Completions()), embeddings=Embeddings(), closed=False)
    tracing = RecordingTracing()
    client = TracedOpenAI(inner, tracing)
    schema = {"type": "json_schema", "json_schema": {"name": "spec_selection"}}

    await client.chat.completions.create(model="m", messages=[], response_format=schema)
    await client.embeddings.create(model="e", input=["a", "b"])
    with pytest.raises(TimeoutError):
        await client.chat.completions.create(model="broken", messages=[])

    assert [(g["name"], g["model"], g["as_type"]) for g in tracing.generations] == [
        ("spec_selection", "m", "generation"),
        ("embedding", "e", "embedding"),
        ("chat_completion", "broken", "generation"),
    ]
    assert tracing.generations[0]["usage"] == {"input": 11, "output": 7}
    assert tracing.generations[1]["usage"] == {"input": 5}
    assert "upstream" in tracing.generations[2]["error"]
    assert client.closed is False  # anything else is the inner client's


async def test_an_unreachable_langfuse_never_slows_a_turn():
    tracing = build_tracing(make_settings(**KEYS, langfuse_base_url="http://127.0.0.1:9"))
    agent = agent_with(tool_then_answer(), tracing)

    started = time.perf_counter()
    answer = await agent.ask("u", "s", "q", ToolContext(None, None))

    assert tracing.enabled and answer.content.startswith("Đáp án.")
    assert time.perf_counter() - started < 2


def test_a_failure_is_recorded_by_its_type_only_since_its_message_can_hold_a_secret():
    from personal_kb.infrastructure.tracing import _Recorder

    class Observation:
        def update(self, **fields):
            self.fields = fields

    observation = Observation()
    _Recorder(observation).fail(ConnectionError("Error connecting to redis://:r3dis-pass@memory-redis:6379"))

    assert observation.fields == {"level": "ERROR", "status_message": "ConnectionError"}


def test_the_postgres_password_is_masked_in_traces():
    from personal_kb.infrastructure.tracing import secrets_of

    dsn = "postgresql://u:s3cret-pass@h/db"
    settings = make_settings(**KEYS, postgres_url=dsn)

    assert dsn in secrets_of(settings)
    assert "s3cret-pass" in secrets_of(settings)  # alone too: a log or error may show it without the rest of the DSN
