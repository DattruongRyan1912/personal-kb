"""Markdown-aware chunking of SDD documents (issue 1.2).

Tier 1 splits on `#`, `##`, `###` with LangChain's MarkdownHeaderTextSplitter; every chunk carries the headings of all
its parents. Tier 2 packs a section's blocks into chunks of at most MAX_TOKENS; only a prose block longer than that is
cut, by RecursiveCharacterTextSplitter with OVERLAP_TOKENS of overlap. Tables and code blocks are never cut.

MarkdownHeaderTextSplitter strips every line it returns (code loses its indentation and blank lines, tables gain
trailing spaces), so it only ever sees the heading lines plus one placeholder per block; the blocks are put back
byte-exact afterwards.
"""

import re
from dataclasses import dataclass

import tiktoken
import yaml
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from pydantic import BaseModel

MAX_TOKENS = 800
OVERLAP_TOKENS = 100

_ENCODING = tiktoken.get_encoding("cl100k_base")  # the tokenizer of text-embedding-3-small
_HEADER_LEVELS = [("#", "h1"), ("##", "h2"), ("###", "h3")]
_HEADING = re.compile(r"^#{1,3}\s+\S")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_PLACEHOLDER = "⟦cyberos-block-{}⟧"
_PLACEHOLDER_RE = re.compile(r"⟦cyberos-block-(\d+)⟧")

_header_splitter = MarkdownHeaderTextSplitter(_HEADER_LEVELS, strip_headers=True)
_prose_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base", chunk_size=MAX_TOKENS, chunk_overlap=OVERLAP_TOKENS
)


class SpecChunk(BaseModel):
    spec_id: str
    headings: list[str]
    content: str
    status: str = "APPROVED"
    chunk_index: int  # position in the document; with spec_id it keys the chunk for idempotent upserts
    project_id: str = "Personal-KB"


@dataclass(frozen=True)
class _Block:
    kind: str  # "text" | "table" | "code"
    text: str


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def parse_frontmatter(markdown: str) -> tuple[dict, str]:
    markdown = markdown.replace("\r\n", "\n")  # a spec saved on Windows
    match = _FRONTMATTER.match(markdown)
    if not match:
        return {}, markdown
    return yaml.safe_load(match.group(1)) or {}, markdown[match.end() :]


def chunk_markdown(
    markdown: str, *, spec_id: str, status: str = "APPROVED", project_id: str = "Personal-KB"
) -> list[SpecChunk]:
    blocks: list[_Block] = []
    masked: list[str] = []
    for item in _split_blocks(markdown):
        if isinstance(item, _Block):
            masked.append(_PLACEHOLDER.format(len(blocks)))
            blocks.append(item)
        else:
            masked.append(item)

    chunks: list[SpecChunk] = []
    for section in _header_splitter.split_text("\n\n".join(masked)):
        headings = [f"{marker} {section.metadata[key]}" for marker, key in _HEADER_LEVELS if key in section.metadata]
        section_blocks = [blocks[int(i)] for i in _PLACEHOLDER_RE.findall(section.page_content)]
        for content in _pack(section_blocks):
            chunks.append(
                SpecChunk(
                    spec_id=spec_id,
                    headings=headings,
                    content=content,
                    status=status,
                    chunk_index=len(chunks),
                    project_id=project_id,
                )
            )
    return chunks


def _split_blocks(markdown: str) -> list[str | _Block]:
    """Heading lines (as str) and content blocks, in document order."""
    lines = markdown.splitlines()
    items: list[str | _Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if fence := _FENCE.match(line):
            end = i + 1
            while end < len(lines) and not lines[end].lstrip().startswith(fence.group(1)):
                end += 1
            items.append(_Block("code", "\n".join(lines[i : end + 1])))
            i = end + 1
        elif _HEADING.match(line):
            items.append(line.strip())
            i += 1
        elif not line.strip():
            i += 1
        elif line.lstrip().startswith("|"):
            end = i
            while end < len(lines) and lines[end].lstrip().startswith("|"):
                end += 1
            items.append(_Block("table", "\n".join(lines[i:end])))
            i = end
        else:
            end = i
            while end < len(lines) and lines[end].strip() and not _starts_other_block(lines[end]):
                end += 1
            items.append(_Block("text", "\n".join(lines[i:end])))
            i = end
    return items


def _starts_other_block(line: str) -> bool:
    return bool(_FENCE.match(line) or _HEADING.match(line) or line.lstrip().startswith("|"))


def _pack(blocks: list[_Block]) -> list[str]:
    """Greedily join blocks into chunks of at most MAX_TOKENS; an oversized table or code block stays whole."""
    chunks: list[str] = []
    current: list[str] = []
    for block in blocks:
        candidate = "\n\n".join([*current, block.text])
        if count_tokens(candidate) <= MAX_TOKENS:
            current.append(block.text)
            continue
        if current:
            chunks.append("\n\n".join(current))
            current = []
        if count_tokens(block.text) <= MAX_TOKENS:
            current = [block.text]
        elif block.kind == "text":
            chunks.extend(_prose_splitter.split_text(block.text))
        else:
            chunks.append(block.text)
    if current:
        chunks.append("\n\n".join(current))
    return chunks
