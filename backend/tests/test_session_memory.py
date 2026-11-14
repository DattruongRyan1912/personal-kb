import asyncio
import logging

import fakeredis
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from personal_kb.services.session_memory import SUMMARY_NAME, SessionMemoryManager, TranscriptEntry, count_tokens

USER, OTHER = "user-a", "user-b"


class FakeSummarizer:
    def __init__(self, gate: asyncio.Event | None = None):
        self.calls = []
        self.gate = gate  # when set, summaries wait for it (to append messages meanwhile)
        self.started = asyncio.Event()  # set once a summary is under way (its snapshot already read)

    async def summarize(self, previous, messages):
        self.calls.append((previous, [m.content for m in messages]))
        self.started.set()
        if self.gate:
            await self.gate.wait()
        return f"summary of {len(messages)} messages" + (f" after [{previous}]" if previous else "")


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis()


def manager(redis, summarizer=None, **kw):
    options = {"threshold_tokens": 60, "keep_last": 4, "max_context_tokens": 120} | kw
    return SessionMemoryManager(redis, summarizer=summarizer or FakeSummarizer(), **options)


def words(n: int, tag: str = "w") -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


def tool_turn(call_id: str):
    return [
        AIMessage(content="", tool_calls=[{"id": call_id, "name": "search_sdd_knowledge", "args": {"query": "x"}}]),
        ToolMessage(content=f"result {call_id}", tool_call_id=call_id),
    ]


async def test_messages_round_trip_with_their_roles_and_tool_references(redis):
    m = manager(redis, threshold_tokens=10_000)
    sent = [HumanMessage("Tìm luồng thanh toán"), *tool_turn("call-1"), AIMessage("Đây là SPC-2")]

    await m.add_messages(USER, "s1", sent)

    got = await m.get_history(USER, "s1")
    assert [type(x).__name__ for x in got] == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert got[1].tool_calls[0]["id"] == "call-1" and got[2].tool_call_id == "call-1"


async def test_history_lives_under_the_users_key_for_seven_days(redis):
    await manager(redis).add_messages(USER, "s1", [HumanMessage("hi")])

    assert await redis.exists("session_user-a:s1")
    assert 7 * 24 * 3600 - 5 <= await redis.ttl("session_user-a:s1") <= 7 * 24 * 3600


async def test_a_user_never_reads_another_users_session(redis):
    m = manager(redis)
    await m.add_messages(USER, "s1", [HumanMessage("secret")])

    assert await m.get_history(OTHER, "s1") == []


async def test_sessions_are_listed_per_user_most_recent_first_and_cleared(redis):
    m = manager(redis)
    await m.add_messages(USER, "old", [HumanMessage("a")])
    await asyncio.sleep(0.01)
    await m.add_messages(USER, "new", [HumanMessage("b")])
    await m.add_messages(OTHER, "theirs", [HumanMessage("c")])

    assert [s.session_id for s in await m.list_sessions(USER)] == ["new", "old"]
    await m.clear_session(USER, "new")
    assert [s.session_id for s in await m.list_sessions(USER)] == ["old"]
    assert await m.get_history(USER, "new") == []


async def test_a_short_history_is_not_summarized(redis):
    summarizer = FakeSummarizer()
    m = manager(redis, summarizer)

    await m.add_messages(USER, "s1", [HumanMessage("short"), AIMessage("reply")])
    await m.wait_idle()

    assert summarizer.calls == []


async def test_crossing_the_threshold_summarizes_all_but_the_last_four_in_the_background(redis, caplog):
    caplog.set_level(logging.INFO)
    summarizer = FakeSummarizer()
    m = manager(redis, summarizer)
    turns = [HumanMessage(words(10, f"q{i}")) if i % 2 == 0 else AIMessage(words(10, f"a{i}")) for i in range(8)]

    await m.add_messages(USER, "s1", turns)
    await m.wait_idle()

    assert "[MemoryManager] Context > 60 tokens. Triggering background summarization..." in caplog.text
    history = await m.get_history(USER, "s1")
    assert isinstance(history[0], SystemMessage) and history[0].name == SUMMARY_NAME
    assert history[0].content == "summary of 4 messages"
    assert [x.content for x in history[1:]] == [t.content for t in turns[4:]]


async def test_a_tool_call_and_its_result_are_never_split(redis):
    summarizer = FakeSummarizer()
    m = manager(redis, summarizer)
    # the last four messages would start with a ToolMessage: its AIMessage must stay with it
    history = [
        HumanMessage(words(30)),
        AIMessage(words(30)),
        HumanMessage("q"),
        *tool_turn("c1"),
        AIMessage("a"),
        HumanMessage("q2"),
        AIMessage("a2"),
    ]

    await m.add_messages(USER, "s1", history)
    await m.wait_idle()

    kept = (await m.get_history(USER, "s1"))[1:]
    assert not isinstance(kept[0], ToolMessage)
    call_ids = {c["id"] for x in kept if isinstance(x, AIMessage) for c in x.tool_calls}
    assert all(x.tool_call_id in call_ids for x in kept if isinstance(x, ToolMessage))
    # the last four start at the ToolMessage: its AIMessage is kept too, and the question "q" of that turn
    assert kept[0].content == "q" and len(kept) == 6


async def test_messages_added_during_a_summary_are_kept(redis):
    gate = asyncio.Event()
    summarizer = FakeSummarizer(gate)
    m = manager(redis, summarizer)
    await m.add_messages(USER, "s1", [HumanMessage(words(20, f"m{i}")) for i in range(6)])
    await summarizer.started.wait()  # the background summary has read its snapshot

    await m.add_messages(USER, "s1", [HumanMessage("arrived while summarizing")])
    gate.set()
    await m.wait_idle()

    assert (await m.get_history(USER, "s1"))[-1].content == "arrived while summarizing"


async def test_the_next_summary_folds_in_the_previous_one(redis):
    summarizer = FakeSummarizer()
    m = manager(redis, summarizer)
    await m.add_messages(USER, "s1", [HumanMessage(words(20, f"x{i}")) for i in range(6)])
    await m.wait_idle()

    await m.add_messages(USER, "s1", [HumanMessage(words(20, f"y{i}")) for i in range(6)])
    await m.wait_idle()

    assert summarizer.calls[-1][0] == "summary of 2 messages"
    assert (await m.get_history(USER, "s1"))[0].content.endswith("after [summary of 2 messages]")


async def test_context_for_the_model_stays_under_the_hard_cap_even_before_a_summary(redis):
    m = manager(redis, threshold_tokens=10_000, max_context_tokens=120)
    history = [HumanMessage(words(25, f"h{i}")) for i in range(6)] + tool_turn("c9") + [AIMessage("done")]
    await m.add_messages(USER, "s1", history)

    context = await m.context_for_model(USER, "s1")

    assert count_tokens(context) <= 120
    assert context[-1].content == "done" and isinstance(context[-2], ToolMessage)
    assert not isinstance(context[0], ToolMessage)


async def test_turns_that_arrive_during_a_summary_are_folded_by_a_follow_up_summary(redis):
    gate = asyncio.Event()
    summarizer = FakeSummarizer(gate)
    m = manager(redis, summarizer)
    await m.add_messages(USER, "s1", [HumanMessage(words(20, f"a{i}")) for i in range(6)])
    await summarizer.started.wait()
    for i in range(8):  # a burst while the first summary is still running
        await m.add_messages(USER, "s1", [HumanMessage(words(20, f"b{i}"))])

    gate.set()
    await m.wait_idle()

    history = await m.get_history(USER, "s1")
    assert len(summarizer.calls) >= 2
    assert len(history) == 1 + 4  # one summary plus the last four
    assert history[-1].content == words(20, "b7")


def test_the_kept_tail_starts_at_a_question_so_the_latest_question_is_never_summarized():
    from personal_kb.services.session_memory import _tail_groups

    def reads(call_id):
        return [
            AIMessage("", tool_calls=[{"name": "get_full_spec_content", "args": {}, "id": call_id}]),
            ToolMessage("SPC-1 — Luồng đăng nhập", tool_call_id=call_id),
        ]

    earlier = [HumanMessage("Câu hỏi 1"), AIMessage("Trả lời 1")]
    latest = [HumanMessage("Câu hỏi 2"), *reads("c1"), *reads("c2"), AIMessage("Trả lời 2")]

    assert _tail_groups(earlier + latest, 4) == len(latest)
    assert _tail_groups(earlier + earlier, 4) == 4  # plain turns: the last four messages, as before


async def test_the_transcript_keeps_every_turn_even_after_a_summary(redis):
    m = manager(redis)
    for i in range(4):
        await m.add_messages(USER, "s1", [HumanMessage(words(20, f"q{i}")), AIMessage(words(20, f"a{i}"))])
        await m.add_to_transcript(USER, "s1", [TranscriptEntry("user", f"q{i}"), TranscriptEntry("assistant", f"a{i}")])
    await m.wait_idle()

    assert isinstance((await m.get_history(USER, "s1"))[0], SystemMessage)  # working memory was summarized
    assert [e.content for e in await m.transcript(USER, "s1")] == ["q0", "a0", "q1", "a1", "q2", "a2", "q3", "a3"]
    assert 7 * 24 * 3600 - 5 <= await redis.ttl("transcript_user-a:s1") <= 7 * 24 * 3600


async def test_sessions_are_listed_with_their_first_question_as_title(redis):
    m = manager(redis, threshold_tokens=10_000)
    await m.add_messages(USER, "old", [HumanMessage("a")])
    await m.add_to_transcript(USER, "old", [TranscriptEntry("user", "Luồng thanh toán dùng cổng nào?")])
    await asyncio.sleep(0.01)
    await m.add_messages(USER, "new", [HumanMessage("b")])
    await m.add_to_transcript(USER, "new", [TranscriptEntry("user", "x" * 200)])

    sessions = await m.list_sessions(USER)

    assert [(s.session_id, s.title) for s in sessions] == [
        ("new", "x" * 80 + "…"),
        ("old", "Luồng thanh toán dùng cổng nào?"),
    ]
    assert sessions[0].updated_at > sessions[1].updated_at


async def test_clearing_a_session_removes_its_transcript(redis):
    m = manager(redis)
    await m.add_messages(USER, "s1", [HumanMessage("a")])
    await m.add_to_transcript(USER, "s1", [TranscriptEntry("user", "a")])

    await m.clear_session(USER, "s1")

    assert await m.transcript(USER, "s1") == [] and await m.list_sessions(USER) == []
