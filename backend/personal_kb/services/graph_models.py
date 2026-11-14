"""Knowledge-graph ontology and the LLM output models for graph extraction (issue 1.3).

The models double as the JSON Schema sent to the model as a Structured Output (strict: no extra fields, all required).
Ids are normalized here, after generation, so "bảng users", "Users Table" and "db_table:Users" all land on one node.
"""

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

NodeLabel = Literal["Spec", "Feature", "Database_Table", "API_Endpoint", "Role"]
RelationType = Literal["DEFINES", "CALLS", "MODIFIES", "DEPENDS_ON"]

ID_PREFIX: dict[str, str] = {
    "Spec": "spec",
    "Feature": "feature",
    "Database_Table": "db_table",
    "API_Endpoint": "api",
    "Role": "role",
}


def to_snake(text: str) -> str:
    """Lowercase ASCII snake_case, Vietnamese diacritics dropped: 'Gửi Mail' -> 'gui_mail'."""
    ascii_text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    ascii_text = ascii_text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")


def normalize_id(raw: str) -> str:
    """'<prefix>:<name>' with the name in ASCII snake_case: 'api:POST /api/v1/login' -> 'api:post_api_v1_login'."""
    prefix, separator, name = raw.partition(":")
    if not separator:
        raise ValueError(f"id {raw!r} must look like '<prefix>:<name>'")
    snake = to_snake(name)
    if not snake:
        raise ValueError(f"id {raw!r} has an empty name")
    return f"{prefix.strip().lower()}:{snake}"


def spec_node_id(spec_id: str) -> str:
    return normalize_id(f"spec:{spec_id}")


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: NodeLabel

    @model_validator(mode="after")
    def _normalize(self) -> "Node":
        self.id = normalize_id(self.id)
        expected = ID_PREFIX[self.label]
        if not self.id.startswith(f"{expected}:"):
            raise ValueError(f"a {self.label} id must start with '{expected}:', got {self.id!r}")
        return self


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    target_id: str
    relation_type: RelationType

    @field_validator("source_id", "target_id")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_id(value)


class GraphExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[Node]
    edges: list[Edge]

    @model_validator(mode="after")
    def _consistent(self) -> "GraphExtraction":
        unique: dict[str, Node] = {}
        for node in self.nodes:
            unique.setdefault(node.id, node)
        self.nodes = list(unique.values())
        dangling = sorted({e for edge in self.edges for e in (edge.source_id, edge.target_id)} - unique.keys())
        if dangling:
            raise ValueError(f"edges refer to nodes that are not listed: {', '.join(dangling)}")
        return self
