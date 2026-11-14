"""Citations in answers (issue 2.4), checked against what the tools returned.

The agent is told to cite as "[Tên tài liệu](SPEC_ID)"; a model that cites "[SPC-4]" or "(SPC-4)" instead is citing
all the same, so those forms are checked too. A bare id there must look like a spec id (letters, then a hyphen- or
underscore-separated part ending in digits: SPC-4, SDD_CORE_002), so "[x]", "[1]" or "(HTTP 401)" are not citations.
"""

import re
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from personal_kb.tools.sdd_knowledge import sources_in

_LINK = re.compile(r"\[[^\]\n]+\]\(([A-Za-z0-9_.-]{1,64})\)")
_SPEC_ID = r"[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*[-_]\d+[A-Za-z0-9]*"
_BARE = re.compile(rf"[\[(]\s*({_SPEC_ID}(?:\s*[,;]\s*{_SPEC_ID})*)\s*[\])](?!\()")
# tools whose output names specs without their content: listing a spec is not reading it
NOT_EVIDENCE = {"list_sdd_specs"}


def cited_spec_ids(text: str) -> list[str]:
    """Spec ids the text cites: link targets, then ids standing alone in brackets or parentheses."""
    ids = _LINK.findall(text)
    for group in _BARE.findall(_LINK.sub("", text)):
        ids += re.split(r"\s*[,;]\s*", group)
    return list(dict.fromkeys(ids))


_SUB_BLOCK_PREFIXES = (
    "UC-",
    "UC_",
    "DOCX_",
    "DOCX-",
    "TABLE_",
    "TABLE-",
    "PRG-",
    "PRG_",
    "REQ-",
    "REQ_",
    "SEC-",
    "SEC_",
    "FIG-",
    "EPIC-",
)


def unknown_citations(answer: AIMessage, context: Sequence[BaseMessage]) -> list[str]:
    """Spec ids the answer cites that nothing in the context backs: likely invented.

    Only tool results back a citation: the specs as read, in this turn or an earlier one still in the history. Not
    the user's words (naming SPC-1 in a question does not make an answer about it true), not the session summary
    nor earlier answers (they may be wrong, and an answer copied from them was), not the spec catalog (it lists ids,
    not what the specs say).
    """
    backing = [m for m in context if isinstance(m, ToolMessage) and m is not answer and m.name not in NOT_EVIDENCE]
    # a tool result backs the specs it returned, not one its text merely mentions; matched whole: SPC-12 is not SPC-1
    returned = {spec_id for m in backing for spec_id in sources_in(str(m.content))}
    backing_text = "\n".join(str(m.content) for m in backing)

    unknown: list[str] = []
    for spec_id in cited_spec_ids(str(answer.content)):
        if spec_id in returned:
            continue
        # Sub-blocks (UC-*, DOCX_*, etc.) that actually exist in the read specs are valid internal references,
        # not hallucinations
        if spec_id.upper().startswith(_SUB_BLOCK_PREFIXES) and spec_id in backing_text:
            continue
        unknown.append(spec_id)
    return unknown
