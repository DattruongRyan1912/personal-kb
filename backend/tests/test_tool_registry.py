import asyncio
import logging

import pytest
from pydantic import BaseModel, Field, ValidationError

from personal_kb.core.exceptions import DependencyUnavailableError
from personal_kb.tools.base import BaseAgentTool, ToolContext
from personal_kb.tools.registry import ToolRegistry

CTX = ToolContext(retriever=None, documents=None)


class EchoArgs(BaseModel):
    text: str = Field(description="Text to echo back")


class EchoTool(BaseAgentTool):
    name: str = "echo_text"
    description: str = "Lặp lại nguyên văn đoạn text người dùng đưa vào, dùng để kiểm tra registry hoạt động."
    args_schema: type[BaseModel] = EchoArgs

    async def run(self, args: EchoArgs, ctx: ToolContext) -> str:
        return args.text


class BrokenTool(EchoTool):
    name: str = "broken_tool"

    async def run(self, args, ctx):
        raise RuntimeError("boom")


class DownTool(EchoTool):
    name: str = "down_tool"

    async def run(self, args, ctx):
        raise DependencyUnavailableError("qdrant", "connection refused")


class SlowTool(EchoTool):
    name: str = "slow_tool"

    async def run(self, args, ctx):
        await asyncio.sleep(5)
        return "late"


def test_the_package_tools_are_discovered():
    registry = ToolRegistry.discover()

    assert {"search_sdd_knowledge", "get_full_spec_content"} <= set(registry.names)


def test_schemas_follow_openai_function_calling():
    registry = ToolRegistry([EchoTool()])

    [schema] = registry.openai_schemas()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo_text"
    assert schema["function"]["description"].startswith("Lặp lại")
    params = schema["function"]["parameters"]
    assert params["type"] == "object" and params["required"] == ["text"]
    assert params["properties"]["text"]["description"] == "Text to echo back"


def test_a_tool_without_a_description_fails_validation():
    class NoDescription(BaseAgentTool):
        name: str = "no_description"
        args_schema: type[BaseModel] = EchoArgs

    with pytest.raises(ValidationError, match="description"):
        NoDescription()


def test_a_description_under_ten_words_fails_validation():
    class Terse(EchoTool):
        description: str = "Tìm tài liệu."

    with pytest.raises(ValidationError, match="10 words"):
        Terse()


def test_two_tools_with_one_name_are_refused():
    with pytest.raises(ValueError, match="echo_text"):
        ToolRegistry([EchoTool(), EchoTool()])


async def test_execute_runs_the_tool_with_validated_arguments():
    assert await ToolRegistry([EchoTool()]).execute("echo_text", {"text": "xin chào"}, CTX) == "xin chào"


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        (EchoTool(), {"wrong": 1}, "tham số không hợp lệ"),
        (BrokenTool(), {"text": "x"}, "gặp sự cố"),
        (DownTool(), {"text": "x"}, "không kết nối được"),
    ],
)
async def test_a_failing_tool_answers_with_text_instead_of_raising(tool, args, expected, caplog):
    caplog.set_level(logging.WARNING)

    answer = await ToolRegistry([tool]).execute(tool.name, args, CTX)

    assert answer.startswith("Lỗi:") and expected in answer


async def test_a_slow_tool_times_out_with_text():
    answer = await ToolRegistry([SlowTool(timeout_seconds=0.05)]).execute("slow_tool", {"text": "x"}, CTX)

    assert answer.startswith("Lỗi:") and "quá thời gian" in answer


async def test_an_unknown_tool_answers_with_text():
    answer = await ToolRegistry([EchoTool()]).execute("no_such_tool", {}, CTX)

    assert answer.startswith("Lỗi:") and "no_such_tool" in answer
