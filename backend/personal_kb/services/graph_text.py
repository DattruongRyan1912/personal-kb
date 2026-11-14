"""Graph facts as text a re-ranker and an LLM read well (issue 1.4).

The machine form "API_Endpoint post_api_v1_x -[MODIFIES]-> Database_Table y" scored 0.19 against the question
"API gửi mail đăng ký ảnh hưởng đến bảng nào?" on bge-reranker-v2-m3; Vietnamese phrases that keep the ontology tag,
"API POST /api/v1/x: - ghi vào bảng y (MODIFIES)", scored 0.65. The team asks in Vietnamese, so facts read that way.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_LABEL_WORD = {"Database_Table": "bảng", "Feature": "tính năng", "Role": "vai trò"}

_RELATION_WORDS = {  # relation -> (outgoing, incoming)
    "DEFINES": ("định nghĩa", "được định nghĩa trong"),
    "CALLS": ("gọi", "được gọi bởi"),
    "MODIFIES": ("ghi vào", "bị ghi bởi"),
    "DEPENDS_ON": ("phụ thuộc vào", "là phụ thuộc của"),
}


def display_name(label: str, name: str) -> str:
    if (
        label == "API_Endpoint"
    ):  # "post_api_v1_auth_login" -> "POST /api/v1/auth/login" (underscores inside a segment are lost)
        method, _, path = name.partition("_")
        return f"API {method.upper()} /{path.replace('_', '/')}"
    if label == "Spec":  # "spc_3" -> "SPC-3"
        return f"spec {name.replace('_', '-').upper()}"
    if label == "Feature":
        return f"tính năng {name.replace('_', ' ')}"
    return f"{_LABEL_WORD.get(label, label)} {name}"


def relation_line(relation: str, outgoing: bool, other: str) -> str:
    out_word, in_word = _RELATION_WORDS[relation]
    return f"- {out_word if outgoing else in_word} {other} ({relation})"


@dataclass(frozen=True)
class GraphFact:
    """A matched node and its one-hop links, as text a re-ranker and an LLM can read."""

    node_id: str
    text: str
    spec_ids: list[str]


def graph_fact(record: Mapping[str, Any]) -> GraphFact:
    """One neighbourhood record (id, label, name, spec_ids, links) as text; every graph store builds the same one."""
    head = display_name(record["label"], record["name"])
    lines = []
    spec_ids = list(record["spec_ids"])
    for link in record["links"]:
        other = display_name(link["other_label"], link["other_name"])
        lines.append(relation_line(link["type"], link["outgoing"], other))
        spec_ids += [s for s in link["spec_ids"] if s not in spec_ids]
    text = "\n".join([f"{head}:", *lines]) if lines else head
    return GraphFact(node_id=record["id"], text=text, spec_ids=spec_ids)
