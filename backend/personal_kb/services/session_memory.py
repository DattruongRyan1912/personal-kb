"""Working memory of a chat session in Redis, kept small by a sliding window plus a rolling summary (issue 2.1).

A session is one JSON array of LangChain messages under `session_{user_id}:{session_id}` (decision 3 on #266: keyed by
user, so nobody reads another user's session), expiring 7 days after its last write; `sessions_{user_id}` indexes a
user's sessions by last use. When the history passes threshold_tokens, a background task folds everything but the
last keep_last messages into one system message named Summary_Context.

Beside it, `transcript_{user_id}:{session_id}` keeps what the chat window shows, every question and answer and never
summarized, so a reloaded page shows the whole conversation (issue 3.2); same expiry, cleared with the session.

A tool call and its results are one group that is never split (a ToolMessage without its AIMessage, or the reverse,
is an HTTP 400 at OpenAI). A summary written while new messages arrived keeps them. context_for_model() caps what is
sent to the model at max_context_tokens even before a summary lands.
"""

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

import tiktoken
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from redis.asyncio import Redis
from redis.exceptions import WatchError

log = logging.getLogger(__name__)

SUMMARY_NAME = "Summary_Context"
SESSION_TTL_SECONDS = 7 * 24 * 3600
_ENCODING = tiktoken.get_encoding("o200k_base")  # gpt-4o-mini's tokenizer
_MESSAGE_OVERHEAD = 4  # role and separators per message, as OpenAI counts them
_MAX_SUMMARY_ROUNDS = 5
_TITLE_CHARS = 80


@dataclass(frozen=True)
class TranscriptEntry:
    role: Literal["user", "assistant"]
    content: str
    stopped: bool = False  # the user stopped the answer: content is what was shown


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    title: str  # the first question
    updated_at: float  # unix time of the last write


class Summarizer(Protocol):
    async def summarize(self, previous: str | None, messages: Sequence[BaseMessage]) -> str: ...


def count_tokens(messages: Sequence[BaseMessage]) -> int:
    total = 0
    for message in messages:
        content = message.content if isinstance(message.content, str) else json.dumps(message.content)
        total += _MESSAGE_OVERHEAD + len(_ENCODING.encode(content))
        if isinstance(message, AIMessage) and message.tool_calls:
            total += len(_ENCODING.encode(json.dumps(message.tool_calls, ensure_ascii=False)))
    return total


def _groups(messages: Sequence[BaseMessage]) -> list[list[BaseMessage]]:
    """Messages in units that must stay together: an AIMessage with tool calls plus the ToolMessages answering it."""
    groups: list[list[BaseMessage]] = []
    for message in messages:
        if isinstance(message, ToolMessage) and groups and _answers(groups[-1], message):
            groups[-1].append(message)
        else:
            groups.append([message])
    return groups


def _answers(group: list[BaseMessage], tool_message: ToolMessage) -> bool:
    head = group[0]
    return isinstance(head, AIMessage) and tool_message.tool_call_id in {c["id"] for c in head.tool_calls}


def _split_summary(messages: list[BaseMessage]) -> tuple[SystemMessage | None, list[BaseMessage]]:
    if messages and isinstance(messages[0], SystemMessage) and messages[0].name == SUMMARY_NAME:
        return messages[0], messages[1:]
    return None, messages


def _tail_groups(body: list[BaseMessage], at_least: int) -> int:
    """How many trailing messages to keep: whole groups covering at least `at_least` messages, from a user's question
    on, so the question of a turn that read several specs is never folded into the summary without its answer."""
    kept = 0
    for group in reversed(_groups(body)):
        kept += len(group)
        if kept >= at_least and isinstance(group[0], HumanMessage):
            break
    return kept


def _dump(messages: Sequence[BaseMessage]) -> str:
    return json.dumps(messages_to_dict(messages), ensure_ascii=False)


class SessionMemoryManager:
    def __init__(
        self,
        redis: Redis,
        *,
        summarizer: Summarizer,
        threshold_tokens: int = 3000,
        keep_last: int = 4,
        max_context_tokens: int = 4000,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._summarizer = summarizer
        self._threshold = threshold_tokens
        self._keep_last = keep_last
        self._max_context = max_context_tokens
        self._ttl = ttl_seconds
        self._running: dict[str, asyncio.Task] = {}

    @staticmethod
    def key(user_id: str, session_id: str) -> str:
        return f"session_{user_id}:{session_id}"

    @staticmethod
    def _index(user_id: str) -> str:
        return f"sessions_{user_id}"

    async def get_history(self, user_id: str, session_id: str) -> list[BaseMessage]:
        return self._load(await self._redis.get(self.key(user_id, session_id)))

    async def add_messages(self, user_id: str, session_id: str, messages: Sequence[BaseMessage]) -> None:
        key = self.key(user_id, session_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            while True:
                try:
                    await pipe.watch(key)
                    history = self._load(await pipe.get(key)) + list(messages)
                    pipe.multi()
                    pipe.set(key, _dump(history), ex=self._ttl)
                    pipe.zadd(self._index(user_id), {session_id: time.time()})
                    pipe.expire(self._index(user_id), self._ttl)
                    await pipe.execute()
                    break
                except WatchError:
                    continue
        if count_tokens(history) > self._threshold and key not in self._running:
            log.info("[MemoryManager] Context > %d tokens. Triggering background summarization...", self._threshold)
            task = asyncio.create_task(self._summarize(key))
            self._running[key] = task
            task.add_done_callback(lambda _t, k=key: self._running.pop(k, None))

    async def clear_session(self, user_id: str, session_id: str) -> None:
        await self._redis.delete(self.key(user_id, session_id), self.transcript_key(user_id, session_id))
        await self._redis.zrem(self._index(user_id), session_id)

    @staticmethod
    def transcript_key(user_id: str, session_id: str) -> str:
        return f"transcript_{user_id}:{session_id}"

    async def add_to_transcript(self, user_id: str, session_id: str, entries: Sequence[TranscriptEntry]) -> None:
        key = self.transcript_key(user_id, session_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.rpush(key, *(json.dumps(asdict(e), ensure_ascii=False) for e in entries))
            pipe.expire(key, self._ttl)
            pipe.zadd(self._index(user_id), {session_id: time.time()})
            pipe.expire(self._index(user_id), self._ttl)
            await pipe.execute()

    async def transcript(self, user_id: str, session_id: str) -> list[TranscriptEntry]:
        return [
            TranscriptEntry(**json.loads(raw))
            for raw in await self._redis.lrange(self.transcript_key(user_id, session_id), 0, -1)
        ]

    async def list_sessions(self, user_id: str) -> list[SessionInfo]:
        """The user's live sessions, most recently used first, titled by their first question."""
        ranked = [
            (i.decode() if isinstance(i, bytes) else i, score)
            for i, score in await self._redis.zrevrange(self._index(user_id), 0, -1, withscores=True)
        ]
        async with self._redis.pipeline(transaction=False) as pipe:
            for session_id, _ in ranked:
                pipe.exists(self.key(user_id, session_id), self.transcript_key(user_id, session_id))
                pipe.lindex(self.transcript_key(user_id, session_id), 0)
            replies = await pipe.execute()
        sessions = []
        for (session_id, score), exists, first in zip(ranked, replies[::2], replies[1::2], strict=True):
            if exists:
                title = json.loads(first)["content"] if first else ""
                if len(title) > _TITLE_CHARS:
                    title = title[:_TITLE_CHARS] + "…"
                sessions.append(SessionInfo(session_id, title, score))
        return sessions

    async def context_for_model(self, user_id: str, session_id: str) -> list[BaseMessage]:
        """The history to send: summary first, then the newest whole groups within max_context_tokens."""
        summary, body = _split_summary(await self.get_history(user_id, session_id))
        head = [summary] if summary else []
        kept: list[BaseMessage] = []
        for group in reversed(_groups(body)):
            if count_tokens(head + group + kept) > self._max_context:
                break
            kept = group + kept
        return head + kept

    async def wait_idle(self) -> None:
        """Wait for background summaries (tests, shutdown)."""
        while self._running:
            await asyncio.gather(*list(self._running.values()), return_exceptions=True)

    async def _summarize(self, key: str) -> None:
        """Fold older messages until the history is under the threshold: turns that arrived while one summary ran
        (a summary takes seconds, a burst of turns does not) are folded by the next round."""
        try:
            for _ in range(_MAX_SUMMARY_ROUNDS):
                snapshot = self._load(await self._redis.get(key))
                if count_tokens(snapshot) <= self._threshold:
                    return
                summary, body = _split_summary(snapshot)
                keep = _tail_groups(body, self._keep_last)
                older = body[: len(body) - keep]
                if not older:
                    return
                text = await self._summarizer.summarize(summary.content if summary else None, older)
                prefix = ([summary] if summary else []) + older
                if not await self._replace_prefix(key, prefix, SystemMessage(content=text, name=SUMMARY_NAME)):
                    return
        except Exception:
            log.exception("[MemoryManager] summarization of %s failed; the history is unchanged", key)

    async def _replace_prefix(self, key: str, prefix: list[BaseMessage], summary: SystemMessage) -> bool:
        """Swap the summarized prefix for the summary, keeping whatever was appended meanwhile."""
        expected = messages_to_dict(prefix)
        async with self._redis.pipeline(transaction=True) as pipe:
            while True:
                try:
                    await pipe.watch(key)
                    current = self._load(await pipe.get(key))
                    if messages_to_dict(current[: len(prefix)]) != expected:
                        log.warning("[MemoryManager] %s changed under the summary; skipped", key)
                        return False
                    pipe.multi()
                    pipe.set(key, _dump([summary, *current[len(prefix) :]]), ex=self._ttl)
                    await pipe.execute()
                    return True
                except WatchError:
                    continue

    @staticmethod
    def _load(raw: bytes | str | None) -> list[BaseMessage]:
        return messages_from_dict(json.loads(raw)) if raw else []
