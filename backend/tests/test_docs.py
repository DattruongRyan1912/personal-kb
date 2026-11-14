"""The handover docs (issue 4.4) stay true to the code: every prompt is in the dictionary, the add-a-tool guide's
code runs as written, the README links the docs."""

import importlib.util
import re
from pathlib import Path

from personal_kb.tools.base import ToolContext
from personal_kb.tools.registry import ToolRegistry

AI = Path(__file__).resolve().parents[2]
DOCS = AI / "docs"


def read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def code_blocks(text: str, language: str) -> list[str]:
    return re.findall(rf"```{language}\n(.*?)```", text, re.DOTALL)


def test_every_prompt_file_is_in_the_dictionary():
    prompts = sorted(p.name for p in (AI / "backend" / "prompts").glob("*.yaml"))

    assert prompts and [p for p in prompts if f"## {p}" not in read("prompts.md")] == []


async def test_the_hello_world_tool_of_the_guide_works_as_written(tmp_path):
    tool_code, test_code = code_blocks(read("add-a-tool.md"), "python")[:2]
    path = tmp_path / "hello_world.py"
    path.write_text(tool_code, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("hello_world_from_the_guide", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tool = module.HelloWorld()

    assert await tool.execute({"name": "An"}, ToolContext(None, None)) == "Hello World, An!"
    assert (await tool.execute({}, ToolContext(None, None))).startswith("Lỗi: tham số không hợp lệ")
    assert ToolRegistry([tool]).status_text("hello_world", {"name": "An"}) == "👋 Đang chào An..."
    assert "from personal_kb.tools.hello_world import HelloWorld" in test_code


def test_the_architecture_is_drawn_in_mermaid():
    assert len(code_blocks(read("architecture.md"), "mermaid")) >= 4


def test_the_readme_links_every_doc():
    readme = (AI / "README.md").read_text(encoding="utf-8")

    assert [d.name for d in DOCS.glob("*.md") if f"docs/{d.name}" not in readme] == []
