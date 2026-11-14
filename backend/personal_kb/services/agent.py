"""The agent: a LangGraph ReAct state machine over the tool registry, with the session's working memory (issue 2.3).

Agent_Thinking sends the persona, the history and the bound tools to the model. If the model asks for a tool, the
flow goes to Tool_Executor, which runs it and comes back; if it answers in text, the run ends. One tool call per turn
(parallel_tool_calls=False, and a reply that still carries several is cut to the first), at most max_tool_calls per
question (AGENT_MAX_TOOL_CALLS): past that the agent stops with an explanation instead of looping (and instead of
LangGraph's recursion error). RECURSION_LIMIT leaves room for the highest limit settings allow.

When a question's first tool call goes to the SDD knowledge, that round also reads whole the specs the question
needs, picked from the catalog. Measured on a six-step scenario with qwen3:8b: more tool calls alone kept the answer
as poor (1.25/10, the agent searched step by step) and so did telling it to read the specs whole; given the specs to
read, it covered far more. A greeting calls no tool, so it reads nothing; once the tools have run, the answering model
(LLM_MODEL_THOROUGH when set) takes over.
"""

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from personal_kb.infrastructure.tracing import Tracing
from personal_kb.services.citations import cited_spec_ids, unknown_citations
from personal_kb.services.grounding import unsupported_terms
from personal_kb.services.guardrails import REFUSAL, blocked_reason
from personal_kb.services.session_memory import SUMMARY_NAME, SessionMemoryManager, TranscriptEntry, count_tokens
from personal_kb.tools.base import ToolContext
from personal_kb.tools.registry import ToolRegistry
from personal_kb.tools.sdd_knowledge import sources_in

log = logging.getLogger(__name__)

AGENT_NODE = "Agent_Thinking"
TOOL_NODE = "Tool_Executor"
CATALOG_TOOL, READ_TOOL = "list_sdd_specs", "get_full_spec_content"
# a call to one of these is a question about the specs: its first tool round also reads them whole; a tool added for
# something else (a Jira lookup, an HR API) runs alone (docs/add-a-tool.md)
SDD_TOOLS = {"search_sdd_knowledge", READ_TOOL, CATALOG_TOOL, "verify_citation"}
CHOOSING = "🧭 Đang chọn các spec liên quan để đọc nguyên văn..."
# per question, the catalog and the specs read included: answers graded right used 3-7 (proposed on #268; the 5
# agreed on #266, point 7, was for an agent that only searched)
MAX_TOOL_CALLS = 12
MAX_READS = 8  # specs read whole per question, picked from the catalog
MAX_TOOL_CALLS_CEILING = 50  # the highest AGENT_MAX_TOOL_CALLS settings accept
RECURSION_LIMIT = 2 * MAX_TOOL_CALLS_CEILING + 2  # a backstop: each tool round is two steps, plus the first and last
# the session summary condenses earlier turns; read as fact, a wrong answer kept in it was repeated by later turns
SUMMARY_NOTICE = (
    "Tóm tắt hội thoại trước, chỉ để hiểu ngữ cảnh (người dùng đã hỏi gì, nói về spec nào). Đây không phải nguồn "
    "thông tin kỹ thuật và có thể sai: mọi thông tin kỹ thuật phải lấy từ nội dung spec do công cụ trả về.\n\n"
)
SPECS_READ = (
    "Ngay sau câu hỏi dưới đây, các spec liên quan được đọc nguyên văn. Trả lời dựa trên nội dung đó, đối chiếu từng "
    "ý với spec, không chép lại câu trả lời trước; chỉ gọi thêm công cụ khi còn thiếu thông tin."
)


class Selector(Protocol):
    async def select(self, question: str, catalog: str, limit: int) -> list[str]: ...


CORRECTION = (
    "Câu trả lời vừa rồi trích mã spec chưa được công cụ trả về: {ids}. Không được trả lời từ kiến thức có sẵn. "
    "Hãy gọi search_sdd_knowledge (hoặc get_full_spec_content nếu đã có mã spec) rồi chỉ trả lời theo kết quả; "
    "nếu không tìm thấy, nói rõ là Hệ thống không có Spec này."
)
NO_SPEC_PREFIX = "Hệ thống không có Spec"  # how the persona's hard rule tells the model to say it
GROUNDING = (
    "Câu trả lời vừa rồi dùng {terms}, nhưng nội dung spec đã đọc không có. Không tự đặt ra mã lỗi, mã HTTP, trạng "
    "thái, API hay bảng. Viết lại câu trả lời, không gọi thêm công cụ: bỏ các tên đó; điểm nào spec không quy định "
    'thì ghi rõ "spec không quy định".'
)
UNVERIFIED = "\n\n⚠️ Chưa kiểm chứng: {terms} không có trong nội dung spec đã đọc, có thể không đúng."
# streaming (issue 3.1): what the client shows while the agent works
THINKING = "🤔 Đang phân tích câu hỏi..."
SYNTHESIZING = "🧠 Đang tổng hợp câu trả lời..."
REASONING = "🧠 Đang suy luận kỹ, có thể mất vài phút..."  # the thorough model thinks before its first word
CHECKING = "🔎 Đang đối chiếu mã lỗi, API và bảng với spec..."
CHECKING_CITATIONS = "🔎 Đang đối chiếu trích dẫn với spec đã đọc..."
STREAM_ERROR = "Xin lỗi, hệ thống AI đang gặp sự cố hoặc phản hồi quá lâu. Hãy thử lại sau ít phút."
NOT_SAVED = "Câu trả lời ở trên chưa được lưu vào lịch sử (bộ nhớ phiên đang gặp sự cố): tải lại trang sẽ mất nó."
RESET = {"type": "reset"}  # drop the text streamed so far: it was a draft (text before a tool call, a replaced answer)
DONE = {"type": "done"}
NO_SPEC_ANSWER = (
    "Hệ thống không có Spec nào về nội dung này, nên tôi không trả lời để tránh đưa thông tin sai. "
    "Bạn có thể hỏi về một luồng nghiệp vụ, API hoặc bảng dữ liệu cụ thể."
)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    tool_calls_made: int


def build_agent_graph(
    model: BaseChatModel,
    tools: ToolRegistry,
    ctx: ToolContext,
    *,
    persona: str,
    max_tool_calls: int = MAX_TOOL_CALLS,
    selector: Selector | None = None,
    answer_model: BaseChatModel | None = None,
    reads: int = MAX_READS,
):
    """model decides what a question needs: it answers small talk and follow-ups itself or asks for a tool;
    answer_model (model when unset) answers once the tools have run. Without a selector, nothing is read up front."""
    lc_tools = tools.as_langchain_tools(ctx)
    by_name = {t.name: t for t in lc_tools}

    def bind(chat_model: BaseChatModel):
        return chat_model.bind_tools(lc_tools, parallel_tool_calls=False) if lc_tools else chat_model

    deciding = bind(model)
    answering = bind(answer_model) if answer_model is not None else deciding
    reading = selector is not None and CATALOG_TOOL in by_name and READ_TOOL in by_name

    async def think(state: AgentState) -> dict:
        after_tools = _tools_ran_this_turn(state["messages"])
        messages = [_labelled(m) for m in state["messages"]]
        if reading and after_tools:  # derive the answer again from the specs: an earlier answer in view was copied
            turn_start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
            messages = [_hidden(m) for m in messages[:turn_start]] + messages[turn_start:]
        prompt = [SystemMessage(persona), *messages]
        if reading and after_tools:  # right before the question: a small model heeds it there, not in the persona
            question = max(i for i, m in enumerate(prompt) if isinstance(m, HumanMessage))
            prompt.insert(question, SystemMessage(SPECS_READ))
        bound = answering if after_tools else deciding
        reply = await bound.ainvoke(prompt)
        if not reply.tool_calls and (unknown := unknown_citations(reply, state["messages"])):
            # an answer citing specs nothing returned is invented (issue 2.4): ask once more, without keeping it
            log.warning("[Citation] %s cited %s without a source: asked again", AGENT_NODE, ", ".join(unknown))
            await adispatch_custom_event("status", {"message": CHECKING_CITATIONS})
            reply = await bound.ainvoke([*prompt, reply, HumanMessage(CORRECTION.format(ids=", ".join(unknown)))])
            if not reply.tool_calls and unknown_citations(reply, state["messages"]):
                log.warning("[Citation] still unsourced: answered that no spec covers it")
                reply = AIMessage(NO_SPEC_ANSWER)
        if not reply.tool_calls and (invented := unsupported_terms(reply, state["messages"])):
            reply = await grounded(bound, prompt, reply, invented, state["messages"])
        if reply.tool_calls and state["tool_calls_made"] >= max_tool_calls:
            log.warning("[Agent] %s wanted a tool after %d calls: stopped", AGENT_NODE, max_tool_calls)
            return {
                "messages": [
                    AIMessage(
                        f"Tôi đã dừng sau {max_tool_calls} lần tra cứu (giới hạn an toàn) mà chưa đủ dữ liệu "
                        "để trả lời chắc chắn. Hãy hỏi cụ thể hơn, ví dụ nêu rõ mã spec."
                    )
                ]
            }
        if len(reply.tool_calls) > 1:
            reply = _first_tool_call_only(reply)
        if reply.tool_calls:
            call = reply.tool_calls[0]
            log.info("[Agent] %s -> %s: %s(%s)", AGENT_NODE, TOOL_NODE, call["name"], call["args"])
        else:
            reply = _with_sources(reply, state["messages"])
            log.info("[Agent] %s -> END", AGENT_NODE)
        return {"messages": [reply]}

    async def grounded(bound, prompt: list, reply: AIMessage, invented: list[str], context: list) -> AIMessage:
        """An answer naming codes, statuses, APIs or tables no spec read states (issue 2.4) is rewritten once, without
        more tools and without keeping it. A rewrite that asks for a tool, cites unread specs or comes back empty is
        not taken; whatever the answer kept still invents is flagged to the reader."""
        log.warning("[Grounding] %s used %s, not in the specs read: asked again", AGENT_NODE, ", ".join(invented))
        await adispatch_custom_event("status", {"message": CHECKING})
        retry = await bound.ainvoke([*prompt, reply, HumanMessage(GROUNDING.format(terms=_listed(invented)))])
        if retry.tool_calls or not str(retry.content).strip() or unknown_citations(retry, context):
            retry, still = reply, invented
        else:
            still = unsupported_terms(retry, context)
        if not still:
            return retry
        log.warning("[Grounding] still not in the specs read: %s (flagged)", ", ".join(still))
        return AIMessage(str(retry.content) + UNVERIFIED.format(terms=_listed(still)))

    async def run_tools(state: AgentState) -> dict:
        last = state["messages"][-1]
        first_round = not _tools_ran_this_turn(state["messages"])
        results: list[BaseMessage] = []
        for call in last.tool_calls:
            tool = by_name.get(call["name"])
            content = await tool.ainvoke(call["args"]) if tool else await tools.execute(call["name"], call["args"], ctx)
            log.info("[Agent] %s ran %s", TOOL_NODE, call["name"])
            results.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
        made = state["tool_calls_made"] + len(last.tool_calls)
        if reading and first_round and any(call["name"] in SDD_TOOLS for call in last.tool_calls):
            read, made = await read_relevant_specs(state["messages"], results, made)
            results += read
        return {"messages": results, "tool_calls_made": made}

    async def read_relevant_specs(messages, results: list[BaseMessage], made: int) -> tuple[list[BaseMessage], int]:
        """The first tool round of a question: the catalog, the specs the selector picks from it for the question,
        each read whole; recorded as the agent's own tool calls (they count against max_tool_calls) so the agent,
        the citation check and the session see them as tool results."""
        question = next(str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage))
        requested = messages[-1].tool_calls
        done = {c["args"].get("spec_id") for c in requested if c["name"] == READ_TOOL}
        catalog = next((str(r.content) for r in results if getattr(r, "name", None) == CATALOG_TOOL), None)
        room = max_tool_calls - made - (catalog is None)
        if room <= 0:
            return [], made
        read: list[BaseMessage] = []

        async def run(name: str, args: dict) -> str:
            call_id = f"reader_{uuid.uuid4().hex[:12]}"
            read.append(AIMessage("", tool_calls=[{"id": call_id, "name": name, "args": args}]))
            content = await by_name[name].ainvoke(args)
            read.append(ToolMessage(content=content, tool_call_id=call_id, name=name))
            return content

        if catalog is None:
            catalog = await run(CATALOG_TOOL, {})
            made += 1
        listed = set(re.findall(r"^- ([A-Za-z0-9_.-]{1,64}): ", catalog, re.MULTILINE))
        await adispatch_custom_event("status", {"message": CHOOSING})
        limit = min(reads, room)
        chosen = [i for i in await selector.select(question, catalog, limit) if i in listed and i not in done]
        chosen = chosen[:limit]
        log.info("[Agent] %s reads %s, picked from the catalog", TOOL_NODE, ", ".join(chosen) or "nothing")
        for spec_id in chosen:
            await run(READ_TOOL, {"spec_id": spec_id})
        return read, made + len(chosen)

    def route(state: AgentState) -> str:
        return TOOL_NODE if state["messages"][-1].tool_calls else END

    graph = StateGraph(AgentState)
    graph.add_node(AGENT_NODE, think)
    graph.add_node(TOOL_NODE, run_tools)
    graph.add_edge(START, AGENT_NODE)
    graph.add_conditional_edges(AGENT_NODE, route, {TOOL_NODE: TOOL_NODE, END: END})
    graph.add_edge(TOOL_NODE, AGENT_NODE)
    return graph.compile()


def _tools_ran_this_turn(messages: Sequence[BaseMessage]) -> bool:
    turn_start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    return any(isinstance(m, ToolMessage) for m in messages[turn_start + 1 :])


def _with_sources(reply: AIMessage, messages: Sequence[BaseMessage]) -> AIMessage:
    """An answer built on specs read this turn but citing none gets a "Nguồn:" line in the citation syntax, so every
    such answer stays traceable (issue 2.4) and the chat UI can render the badges (issue 3.4). Not an answer that no
    spec covers the question: a source line there would contradict it."""
    if cited_spec_ids(str(reply.content)) or str(reply.content).lstrip().startswith(NO_SPEC_PREFIX):
        return reply
    turn_start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1) + 1
    sources: dict[str, str] = {}
    for message in messages[turn_start:]:
        if isinstance(message, ToolMessage):
            for spec_id, title in sources_in(str(message.content)).items():
                sources.setdefault(spec_id, title)
    if not sources:
        return reply
    line = "Nguồn: " + ", ".join(f"[{title}]({spec_id})" for spec_id, title in sources.items())
    return reply.model_copy(update={"content": f"{reply.content}\n\n{line}"})


def _listed(terms: Sequence[str]) -> str:
    return ", ".join(f"`{term}`" for term in terms)


def _first_tool_call_only(reply: AIMessage) -> AIMessage:
    """Keep the first of several tool calls; the model asks again for the others, one turn each."""
    extra = {k: v for k, v in reply.additional_kwargs.items() if k != "tool_calls"}
    return reply.model_copy(update={"tool_calls": reply.tool_calls[:1], "additional_kwargs": extra})


class ChatAgent:
    """One question in a session: memory in, graph run, the new messages (question, tool turns, answer) saved."""

    def __init__(
        self,
        *,
        model: BaseChatModel,
        tools: ToolRegistry,
        memory: SessionMemoryManager | Any,
        persona: str,
        max_tool_calls: int = MAX_TOOL_CALLS,
        selector: Selector | None = None,
        thorough_model: BaseChatModel | None = None,
        tracing: Tracing | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._memory = memory
        self._persona = persona
        self._max_tool_calls = max_tool_calls  # AGENT_MAX_TOOL_CALLS, the specs read included
        self._selector = selector  # picks the specs a question needs, read whole; without it, nothing is read up front
        self._thorough_model = thorough_model  # answers once the specs are read (LLM_MODEL_THOROUGH); else model does
        self._tracing = tracing or Tracing()  # Langfuse (issue 4.1); off: no callbacks, nothing recorded

    def graph(self, ctx: ToolContext):
        return build_agent_graph(
            self._model,
            self._tools,
            ctx,
            persona=self._persona,
            max_tool_calls=self._max_tool_calls,
            selector=self._selector,
            answer_model=self._thorough_model,
        )

    def _config(self) -> dict:
        # run_name names the chain in a trace; callbacks: Langfuse's handler when tracing is on (issue 4.1)
        return {"recursion_limit": RECURSION_LIMIT, "run_name": "agent_chain", "callbacks": self._tracing.callbacks()}

    async def ask(self, user_id: str, session_id: str, text: str | None, ctx: ToolContext) -> AIMessage:
        if not text or not text.strip():
            raise ValueError("an empty question")
        with self._tracing.turn(user_id=user_id, session_id=session_id, question=text.strip()) as turn:
            reason = blocked_reason(text)
            if reason:  # refused before the graph: no tokens spent, nothing written to the session (issue 2.4)
                log.warning("[Guardrail] refused (%s)", reason)
                turn.finish(REFUSAL)
                return AIMessage(REFUSAL)
            history = await self._memory.context_for_model(user_id, session_id)
            inputs = self.initial_state(history, text)
            log.info("[Agent] %d history tokens go to the model", count_tokens(inputs["messages"]))
            result = await self.graph(ctx).ainvoke(inputs, config=self._config())
            new = result["messages"][len(history) :]
            await self._finish(user_id, session_id, new)
            turn.finish(str(new[-1].content))
            return new[-1]

    async def run_once(
        self, user_id: str, session_id: str, text: str, ctx: ToolContext, tags: Sequence[str] = ("eval",)
    ) -> list[BaseMessage]:
        """One question answered from scratch, the session neither read nor written: the turn's messages (question,
        tool calls and results, answer), for the evaluation of issue 4.2."""
        with self._tracing.turn(user_id=user_id, session_id=session_id, question=text.strip(), tags=tags) as turn:
            if blocked_reason(text):
                turn.finish(REFUSAL)
                return [HumanMessage(text.strip()), AIMessage(REFUSAL)]
            result = await self.graph(ctx).ainvoke(self.initial_state([], text), config=self._config())
            turn.finish(str(result["messages"][-1].content))
            return result["messages"]

    async def stream(self, user_id: str, session_id: str, text: str | None, ctx: ToolContext) -> AsyncIterator[dict]:
        """The same turn as ask(), as events for Server-Sent Events (issue 3.1): status, text_delta, reset, error, done.

        A status goes out before anything else, so the first byte never waits for the model. Text streams as the
        model writes it; when a reply turns into a tool call, or the citation check replaces an answer, the client
        is told to reset. The saved answer is the reference: whatever differs from what was streamed is sent last.
        Cancelled (the client left), the run stops and the question is kept with the text the user saw.
        """
        if not text or not text.strip():
            raise ValueError("an empty question")
        yield _status(THINKING)
        with self._tracing.turn(user_id=user_id, session_id=session_id, question=text.strip()) as turn:
            reason = blocked_reason(text)
            if reason:
                log.warning("[Guardrail] refused (%s)", reason)
                turn.finish(REFUSAL)
                yield _delta(REFUSAL)
                yield DONE
                return
            try:
                history = await self._memory.context_for_model(user_id, session_id)
            except Exception as error:
                log.exception("[Agent] the session history could not be read")
                turn.fail(error)
                yield {"type": "error", "message": STREAM_ERROR}
                return
            inputs = self.initial_state(history, text)
            log.info("[Agent] %d history tokens go to the model", count_tokens(inputs["messages"]))
            shown, model_run, final = "", None, None
            try:
                events = self.graph(ctx).astream_events(inputs, config=self._config(), version="v2")
                async with aclosing(events):
                    async for event in events:
                        kind = event["event"]
                        if kind == "on_chat_model_stream" and event["metadata"].get("langgraph_node") == AGENT_NODE:
                            piece = _text_of(event["data"]["chunk"])
                            if not piece:
                                continue
                            if event["run_id"] != model_run:
                                model_run = event["run_id"]
                                if shown:  # a new reply (the citation check asked again) replaces the last one
                                    shown = ""
                                    yield RESET
                            shown += piece
                            yield _delta(piece)
                        elif kind == "on_tool_start":
                            if shown:  # text written before a tool call was not the answer
                                shown = ""
                                yield RESET
                            yield _status(self._tools.status_text(event["name"], event["data"].get("input") or {}))
                        elif kind == "on_custom_event" and event["name"] == "status":
                            if shown:  # the answer is being checked and rewritten: show the status, not the draft
                                shown = ""
                                yield RESET
                            yield _status(event["data"]["message"])
                        elif kind == "on_chain_end" and event["name"] == TOOL_NODE:  # once, the specs read included
                            yield _status(REASONING if self._thorough_model is not None else SYNTHESIZING)
                        elif kind == "on_chain_end" and not event.get("parent_ids"):
                            final = event["data"]["output"]
            except asyncio.CancelledError:
                log.warning("[Agent] run cancelled after %d characters of the answer", len(shown))
                await self._keep_unfinished(user_id, session_id, text.strip(), shown)
                raise
            except Exception as error:
                log.exception("[Agent] streaming run failed")
                turn.fail(error)
                yield {"type": "error", "message": STREAM_ERROR}
                return
            new = final["messages"][len(history) :]
            answer = str(new[-1].content)
            if not answer.startswith(shown):
                shown = ""
                yield RESET
            if answer[len(shown) :]:
                yield _delta(answer[len(shown) :])
            try:
                await self._finish(user_id, session_id, new)
            except Exception as error:
                log.exception("[Agent] the turn could not be saved")
                turn.fail(error)
                yield {"type": "error", "message": NOT_SAVED}
                return
            turn.finish(answer)
            yield DONE

    async def _finish(self, user_id: str, session_id: str, new: Sequence[BaseMessage]) -> None:
        await self._memory.add_messages(user_id, session_id, new)
        await self._memory.add_to_transcript(
            user_id,
            session_id,
            [TranscriptEntry("user", str(new[0].content)), TranscriptEntry("assistant", str(new[-1].content))],
        )
        unknown = unknown_citations(new[-1], new)
        if unknown:
            log.warning("[Citation] the answer cites spec ids no tool returned this turn: %s", ", ".join(unknown))

    async def _keep_unfinished(self, user_id: str, session_id: str, question: str, shown: str) -> None:
        """A stopped turn keeps the question and the part of the answer the user saw, so the next turn has them."""
        try:
            await self._memory.add_messages(
                user_id, session_id, [HumanMessage(question), *([AIMessage(shown)] if shown else [])]
            )
            await self._memory.add_to_transcript(
                user_id,
                session_id,
                [TranscriptEntry("user", question), TranscriptEntry("assistant", shown, stopped=True)],
            )
        except Exception:
            log.exception("[Agent] the stopped turn could not be saved")

    @staticmethod
    def initial_state(history: Sequence[BaseMessage], text: str) -> AgentState:
        return {"messages": [*history, HumanMessage(text.strip())], "tool_calls_made": 0}


def _status(message: str) -> dict:
    return {"type": "status", "message": message}


def _delta(text: str) -> dict:
    return {"type": "text_delta", "delta": text}


def _text_of(chunk: BaseMessage) -> str:
    content = chunk.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


def _hidden(message: BaseMessage) -> BaseMessage:
    """An earlier answer as the agent sees it once the specs are read: which specs it cited, not what it said."""
    if isinstance(message, AIMessage) and message.content:
        cited = ", ".join(cited_spec_ids(str(message.content))) or "không trích spec nào"
        return message.model_copy(update={"content": f"(Câu trả lời trước, đã ẩn; đã trích: {cited})"})
    return message


def _labelled(message: BaseMessage) -> BaseMessage:
    """The session summary as the model sees it: marked as context, not as a source (the stored one is untouched)."""
    if isinstance(message, SystemMessage) and message.name == SUMMARY_NAME:
        return SystemMessage(SUMMARY_NOTICE + str(message.content), name=SUMMARY_NAME)
    return message
