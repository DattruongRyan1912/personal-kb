import fakeredis
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from personal_kb.services.agent import AGENT_NODE, MAX_READS, SPECS_READ, TOOL_NODE, ChatAgent
from personal_kb.services.session_memory import SessionMemoryManager
from personal_kb.tools.base import ToolContext
from personal_kb.tools.registry import ToolRegistry
from tests.test_agent import FakeSpecTool, ScriptedModel, call
from tests.test_agent_stream import StreamingModel


class NoArgs(BaseModel):
    pass


class FakeCatalog(FakeSpecTool):
    name: str = "list_sdd_specs"
    description: str = "Liệt kê mã, tên và người viết của mọi tài liệu Spec trong kho, không kèm nội dung."
    args_schema: type[BaseModel] = NoArgs

    async def run(self, args, ctx):
        return "Danh mục tài liệu SDD (3).\n- SPC-1: Luồng đăng nhập\n- SPC-2: Luồng thanh toán\n- SPC-4: Hồ sơ"


class FakeSelector:
    def __init__(self, ids):
        self.ids, self.asked = ids, []

    async def select(self, question, catalog, limit):
        self.asked.append((question, catalog, limit))
        return self.ids[:limit]


def agent_with(script, ceiling=12, selector=None, model_class=ScriptedModel, thorough_model=None):
    model, tool = model_class(script=script), FakeSpecTool()
    memory = SessionMemoryManager(fakeredis.FakeAsyncRedis(), summarizer=None, threshold_tokens=100_000)
    agent = ChatAgent(
        model=model,
        tools=ToolRegistry([tool, FakeCatalog()]),
        memory=memory,
        persona="p",
        max_tool_calls=ceiling,
        selector=selector,
        thorough_model=thorough_model,
    )
    return agent, model, tool


def ask(agent, text="Kịch bản thanh toán"):
    return agent.ask("u", "s", text, ToolContext(None, None))


def endless_tool_calls():
    return [AIMessage("", tool_calls=[call(f"SPC-{i}", f"c{i}")]) for i in range(60)]


async def test_a_greeting_is_answered_at_once_without_tools_selection_or_the_thorough_model():
    thorough = ScriptedModel(script=[AIMessage("không dùng")])
    selector = FakeSelector(["SPC-1"])
    agent, _, tool = agent_with([AIMessage("Chào bạn!")], selector=selector, thorough_model=thorough)

    answer = await ask(agent, "Chào buổi sáng")

    assert answer.content == "Chào bạn!"
    assert selector.asked == [] and tool.calls == [] and thorough.seen == []


async def test_the_first_tool_round_also_reads_whole_the_specs_the_selector_picks():
    selector = FakeSelector(["SPC-1", "SPC-9", "SPC-2"])  # SPC-9 is not in the catalog, SPC-2 was just read
    thorough = ScriptedModel(script=[AIMessage("Đáp án [Luồng thanh toán](SPC-2).")])
    agent, _, tool = agent_with(
        [AIMessage("", tool_calls=[call("SPC-2", "c1")])], selector=selector, thorough_model=thorough
    )

    answer = await ask(agent)

    assert tool.calls == ["SPC-2", "SPC-1"]
    assert selector.asked[0][0] == "Kịch bản thanh toán" and "SPC-4: Hồ sơ" in selector.asked[0][1]
    read = [m.content for m in thorough.seen[0] if m.type == "tool"]
    assert read[0].endswith("nội dung của SPC-2") and read[-1].endswith("nội dung của SPC-1")
    assert answer.content.startswith("Đáp án")
    saved = await agent._memory.get_history("u", "s")
    assert [m.type for m in saved] == ["human", "ai", "tool", "ai", "tool", "ai", "tool", "ai"]


async def test_later_tool_rounds_read_nothing_more():
    selector = FakeSelector(["SPC-2"])
    script = [
        AIMessage("", tool_calls=[call("SPC-1", "c1")]),
        AIMessage("", tool_calls=[call("SPC-4", "c2")]),
        AIMessage("ok"),
    ]
    agent, _, tool = agent_with(script, selector=selector)

    await ask(agent)

    assert tool.calls == ["SPC-1", "SPC-2", "SPC-4"] and len(selector.asked) == 1


async def test_the_selector_is_asked_for_at_most_its_share_of_reads():
    selector = FakeSelector([f"SPC-{i}" for i in range(1, 20)])
    agent, _, _ = agent_with(
        [AIMessage("", tool_calls=[call("SPC-1", "c1")]), AIMessage("ok")], ceiling=50, selector=selector
    )

    await ask(agent)

    assert selector.asked[0][2] == MAX_READS


async def test_the_catalog_and_the_reads_count_against_the_tool_budget():
    selector = FakeSelector(["SPC-2", "SPC-4", "SPC-1"])
    agent, _, tool = agent_with(endless_tool_calls(), ceiling=4, selector=selector)

    answer = await ask(agent)

    assert selector.asked[0][2] == 2  # four calls: the agent's own, the catalog, then two reads
    assert tool.calls == ["SPC-0", "SPC-2", "SPC-4"]
    assert "sau 4 lần tra cứu" in answer.content


async def test_the_stop_message_asks_for_a_more_precise_question():
    agent, _, tool = agent_with(endless_tool_calls(), ceiling=3)

    answer = await ask(agent)

    assert len(tool.calls) == 3
    assert "sau 3 lần tra cứu" in answer.content and "nêu rõ mã spec" in answer.content
    assert "mức" not in answer.content


async def test_once_the_specs_are_read_earlier_answers_are_hidden_and_a_note_precedes_the_question():
    earlier = [HumanMessage("Lần 6 trả gì?"), AIMessage("Lần 6 trả 200 OK [Luồng đăng nhập](SPC-1).")]
    thorough = ScriptedModel(script=[AIMessage("Lần 6 vẫn 423 [Luồng đăng nhập](SPC-1).")])
    agent, _, _ = agent_with(
        [AIMessage("", tool_calls=[call("SPC-1", "c1")])], selector=FakeSelector(["SPC-1"]), thorough_model=thorough
    )
    await agent._memory.add_messages("u", "s", earlier)

    await ask(agent, "Lần 6 trả gì?")

    prompt = thorough.seen[0]
    answers = [str(m.content) for m in prompt if isinstance(m, AIMessage)]
    assert not any("200 OK" in c for c in answers)
    assert any("đã ẩn" in c and "SPC-1" in c for c in answers)
    notes = [i for i, m in enumerate(prompt) if isinstance(m, SystemMessage) and m.content == SPECS_READ]
    assert len(notes) == 1 and prompt[notes[0] + 1].type == "human"
    assert any(m.type == "tool" for m in prompt)  # this turn's reads are untouched
    saved = await agent._memory.get_history("u", "s")
    assert not any(m.content == SPECS_READ for m in saved)


async def test_a_follow_up_answered_without_tools_keeps_the_earlier_answer_in_view():
    agent, model, _ = agent_with([AIMessage("Ý 2 là…")], selector=FakeSelector(["SPC-1"]))
    await agent._memory.add_messages("u", "s", [HumanMessage("Liệt kê"), AIMessage("1. A\n2. B [X](SPC-1)")])

    await ask(agent, "Giải thích ý 2")

    assert any(isinstance(m, AIMessage) and "2. B" in str(m.content) for m in model.seen[0])


async def test_without_a_thorough_model_the_quick_model_also_answers_after_the_tools():
    agent, model, _ = agent_with([AIMessage("", tool_calls=[call("SPC-1", "c1")]), AIMessage("Đáp án.")])

    assert (await ask(agent)).content == "Đáp án.\n\nNguồn: [Tài liệu SPC-1](SPC-1)"  # cites nothing: sources line
    assert len(model.seen) == 2


def test_the_graph_keeps_the_two_nodes_of_issue_2_3():
    agent, _, _ = agent_with([], selector=FakeSelector([]))

    mermaid = agent.graph(ToolContext(None, None)).get_graph().draw_mermaid()

    assert AGENT_NODE in mermaid and TOOL_NODE in mermaid and "Spec_Reader" not in mermaid


async def test_the_stream_shows_the_reads_then_that_the_thorough_model_may_take_minutes():
    thorough = StreamingModel(script=[AIMessage("Đáp án.")])
    agent, _, _ = agent_with(
        [AIMessage("", tool_calls=[call("SPC-1", "c1")])],
        selector=FakeSelector(["SPC-2"]),
        model_class=StreamingModel,
        thorough_model=thorough,
    )

    events = [e async for e in agent.stream("u", "s", "Kịch bản", ToolContext(None, None))]

    statuses = [e["message"] for e in events if e["type"] == "status"]
    # think, the agent's read, the catalog, choose, the selector's read (fake tools keep ⚙️), then the reasoning
    assert [s.split()[0] for s in statuses] == ["🤔", "⚙️", "⚙️", "🧭", "⚙️", "🧠"]
    assert "vài phút" in statuses[-1]
    assert events[-1] == {"type": "done"}


class HelloArgs(BaseModel):
    name: str


class HelloTool(FakeSpecTool):
    name: str = "hello_world"
    description: str = "Chào một người theo tên, chỉ dùng khi người dùng yêu cầu rõ công cụ chào hỏi này."
    args_schema: type[BaseModel] = HelloArgs

    async def run(self, args, ctx):
        return f"Hello World, {args.name}!"


async def test_a_tool_outside_the_sdd_knowledge_reads_no_spec():
    selector = FakeSelector(["SPC-1"])
    model = ScriptedModel(
        script=[
            AIMessage("", tool_calls=[{"id": "h1", "name": "hello_world", "args": {"name": "An"}}]),
            AIMessage("Hello World, An!"),
        ]
    )
    memory = SessionMemoryManager(fakeredis.FakeAsyncRedis(), summarizer=None, threshold_tokens=100_000)
    spec_tool = FakeSpecTool()
    agent = ChatAgent(
        model=model,
        tools=ToolRegistry([spec_tool, FakeCatalog(), HelloTool()]),
        memory=memory,
        persona="p",
        selector=selector,
    )

    answer = await ask(agent, "Dùng công cụ hello_world để chào An")

    assert answer.content == "Hello World, An!"
    assert selector.asked == [] and spec_tool.calls == []
