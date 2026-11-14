"""Chat of the signed-in user: ask (2.3), stream the answer (3.1), list, read and delete sessions (2.1; 3.2)."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, StringConstraints

from personal_kb.core.auth import CurrentUser, current_user
from personal_kb.services.agent import STREAM_ERROR, ChatAgent
from personal_kb.services.semantic_cache import SemanticCache
from personal_kb.services.session_memory import SessionMemoryManager, TranscriptEntry

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
# no-cache and no proxy buffering: each event must reach the client as soon as it is written
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

# letters, digits, - and _ only: a session id becomes part of a Redis key
SessionId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
User = Annotated[CurrentUser, Depends(current_user)]


def get_memory(request: Request) -> SessionMemoryManager:
    return request.app.state.memory


Memory = Annotated[SessionMemoryManager, Depends(get_memory)]


def get_agent(request: Request) -> ChatAgent:
    return request.app.state.agent


Agent = Annotated[ChatAgent, Depends(get_agent)]


def get_cache(request: Request) -> SemanticCache | None:
    return getattr(request.app.state, "cache", None)


Cache = Annotated[SemanticCache | None, Depends(get_cache)]


class ChatRequest(BaseModel):
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ChatResponse(BaseModel):
    session_id: str
    answer: str


class ChatMessage(BaseModel):
    role: str
    content: str
    name: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class SessionHistory(BaseModel):
    session_id: str
    messages: list[ChatMessage]


class SessionSummary(BaseModel):
    session_id: str
    title: str
    updated_at: float


class SessionList(BaseModel):
    sessions: list[SessionSummary]


class TranscriptMessage(BaseModel):
    role: str
    content: str
    stopped: bool


class Transcript(BaseModel):
    session_id: str
    messages: list[TranscriptMessage]


def to_chat_message(message: BaseMessage) -> ChatMessage:
    content = message.content if isinstance(message.content, str) else str(message.content)
    if isinstance(message, HumanMessage):
        return ChatMessage(role="user", content=content)
    if isinstance(message, ToolMessage):
        return ChatMessage(role="tool", content=content, tool_call_id=message.tool_call_id)
    if isinstance(message, AIMessage):
        calls = [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in message.tool_calls] or None
        return ChatMessage(role="assistant", content=content, tool_calls=calls)
    if isinstance(message, SystemMessage):
        return ChatMessage(role="system", content=content, name=message.name)
    return ChatMessage(role=message.type, content=content)


@router.get("/sessions")
async def list_sessions(user: User, memory: Memory) -> SessionList:
    sessions = await memory.list_sessions(user.id)
    return SessionList(
        sessions=[SessionSummary(session_id=s.session_id, title=s.title, updated_at=s.updated_at) for s in sessions]
    )


@router.get("/sessions/{session_id}/transcript")
async def session_transcript(session_id: SessionId, user: User, memory: Memory) -> Transcript:
    """Every question and answer of the session as the chat window shows them, never summarized (issue 3.2)."""
    entries = await memory.transcript(user.id, session_id)
    return Transcript(
        session_id=session_id,
        messages=[TranscriptMessage(role=e.role, content=e.content, stopped=e.stopped) for e in entries],
    )


@router.get("/sessions/{session_id}/messages")
async def session_history(session_id: SessionId, user: User, memory: Memory) -> SessionHistory:
    messages = await memory.get_history(user.id, session_id)
    return SessionHistory(session_id=session_id, messages=[to_chat_message(m) for m in messages])


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: SessionId, user: User, memory: Memory) -> Response:
    await memory.clear_session(user.id, session_id)
    return Response(status_code=204)


async def _wrap_stream_with_cache(
    events: AsyncIterator[dict],
    cache: SemanticCache,
    query: str,
    project_id: str,
) -> AsyncIterator[dict]:
    accumulated_text: list[str] = []
    async for event in events:
        if event.get("type") == "text_delta" and "delta" in event:
            accumulated_text.append(event["delta"])
        elif event.get("type") == "reset":
            accumulated_text.clear()
        elif event.get("type") == "done":
            full_answer = "".join(accumulated_text)
            if full_answer:
                asyncio.create_task(cache.set(query, full_answer, project_id=project_id))
        yield event


@router.post("")
async def chat(
    body: ChatRequest,
    request: Request,
    user: User,
    agent: Agent,
    cache: Cache = None,
) -> ChatResponse:
    """One question, answered once the agent is done (the streaming endpoint is issue 3.1)."""
    tool_ctx = getattr(request.app.state, "tool_context", None)
    project_id = getattr(tool_ctx, "project_id", "Personal-KB") if tool_ctx else "Personal-KB"
    memory: SessionMemoryManager | None = getattr(request.app.state, "memory", None)
    history = await memory.get_history(user.id, body.session_id) if memory else []

    # Multi-turn context bleed safety: only consult semantic cache when history is empty
    if cache is not None and len(history) == 0:
        cached_hit = await cache.get(body.message, project_id=project_id)
        if cached_hit:
            answer_text = str(cached_hit.get("answer", ""))
            if memory:
                await memory.add_messages(
                    user.id, body.session_id, [HumanMessage(content=body.message), AIMessage(content=answer_text)]
                )
                await memory.add_to_transcript(
                    user.id,
                    body.session_id,
                    [
                        TranscriptEntry(role="user", content=body.message),
                        TranscriptEntry(role="assistant", content=answer_text),
                    ],
                )
            return ChatResponse(session_id=body.session_id, answer=answer_text)

    answer = await agent.ask(user.id, body.session_id, body.message, tool_ctx)
    answer_text = str(answer.content)
    if cache is not None and len(history) == 0 and answer_text:
        asyncio.create_task(cache.set(body.message, answer_text, project_id=project_id))
    return ChatResponse(session_id=body.session_id, answer=answer_text)


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: User,
    agent: Agent,
    cache: Cache = None,
) -> StreamingResponse:
    """The answer as Server-Sent Events: status, text_delta, reset, error and done, each a JSON object (issue 3.1)."""
    tool_ctx = getattr(request.app.state, "tool_context", None)
    project_id = getattr(tool_ctx, "project_id", "Personal-KB") if tool_ctx else "Personal-KB"
    memory: SessionMemoryManager | None = getattr(request.app.state, "memory", None)
    history = await memory.get_history(user.id, body.session_id) if memory else []

    # Multi-turn context bleed safety: only consult semantic cache when history is empty
    if cache is not None and len(history) == 0:
        cached_hit = await cache.get(body.message, project_id=project_id)
        if cached_hit:
            answer_text = str(cached_hit.get("answer", ""))

            async def cached_stream() -> AsyncIterator[dict]:
                yield {"type": "status", "message": "⚡ Trả lời tức thì từ Semantic Cache..."}
                yield {"type": "cached", "cached": True}
                yield {"type": "text_delta", "delta": answer_text}
                yield {"type": "done"}
                if memory:
                    await memory.add_messages(
                        user.id, body.session_id, [HumanMessage(content=body.message), AIMessage(content=answer_text)]
                    )
                    await memory.add_to_transcript(
                        user.id,
                        body.session_id,
                        [
                            TranscriptEntry(role="user", content=body.message),
                            TranscriptEntry(role="assistant", content=answer_text),
                        ],
                    )

            return StreamingResponse(relay(cached_stream()), media_type="text/event-stream", headers=SSE_HEADERS)

    events = agent.stream(user.id, body.session_id, body.message, tool_ctx)
    if cache is not None and len(history) == 0:
        events = _wrap_stream_with_cache(events, cache, body.message, project_id)
    return StreamingResponse(relay(events), media_type="text/event-stream", headers=SSE_HEADERS)


# load balancers and proxies drop a connection idle for about 60 s; a thinking model is silent longer than that
HEARTBEAT_SECONDS = 15.0


async def relay(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    """Runs the agent in its own task and forwards its events. When the client goes away, Starlette stops this
    generator (cancelled while waiting, or closed): the agent's task is cancelled with it, so the model stops."""
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for event in events:
                queue.put_nowait(event)
        except Exception:  # not CancelledError: a client that left gets nothing more
            log.exception("[Chat] the answer stream failed")
            queue.put_nowait({"type": "error", "message": STREAM_ERROR})
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
            except TimeoutError:  # the model is thinking: a comment line keeps proxies from closing the connection
                yield ": ping\n\n"
                continue
            if event is None:
                break
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        if not task.done():
            log.warning("Client disconnected. Cancelling LLM run...")
            task.cancel()
