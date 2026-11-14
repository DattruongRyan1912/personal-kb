"""The ports the long-term memory is built on (PoC-A2, #297): a vector store, a graph store and a document store.

The services (ingestion, graph ingestion, retrieval, the SDD tools) only know these; Postgres + pgvector implements
them (infrastructure/postgres), held to them by the contract test suite (tests/contract). Times are
timezone-aware UTC; an interval is half-open, valid_from <= t < valid_to, and an open one has no valid_to.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from personal_kb.services.chunking import SpecChunk
from personal_kb.services.graph_models import GraphExtraction
from personal_kb.services.graph_text import GraphFact
from personal_kb.services.provenance import SourceRevision


@dataclass(frozen=True)
class EmbeddedChunk:
    key: str  # services/provenance.keyed_chunks
    chunk: SpecChunk
    vector: list[float]


@dataclass(frozen=True)
class ChunkHit:
    spec_id: str
    chunk_key: str
    valid_from: datetime  # (spec_id, chunk_key, valid_from) names one chunk version on every backend
    headings: list[str]
    content: str
    revision: str | None  # the spec revision the chunk was first written in
    score: float  # cosine similarity: higher is nearer
    project_id: str = "Personal-KB"


@dataclass(frozen=True)
class VectorRevisionResult:
    added: int
    closed: int


@dataclass(frozen=True)
class RevisionResult:
    opened: int  # relationships opened by this revision
    closed: int  # relationships closed: every chunk that stated them is gone


@dataclass(frozen=True)
class DeleteResult:
    relationships: int  # deleted: no other source ever stated them
    nodes: int


@dataclass(frozen=True)
class SpecDocument:
    spec_id: str
    title: str
    content: str  # the Markdown file as written, frontmatter included
    project_id: str = "Personal-KB"


class StaleRevisionError(Exception):
    """A graph revision was planned from chunk keys another run has changed since; plan it again (PoC-A2)."""


class VectorStore(Protocol):
    async def ensure(self) -> bool: ...  # True when it was created

    async def known_chunk_keys(self, source_id: str) -> set[str]: ...

    async def apply_revision(
        self, source: SourceRevision, *, added: list[EmbeddedChunk], removed: set[str], observed_at: datetime
    ) -> VectorRevisionResult: ...

    async def set_project(self, source_id: str, project_id: str) -> int: ...  # open chunks moved to the project

    async def delete_source(self, source_id: str) -> int: ...  # chunks deleted, past ones included

    async def tombstone_source(
        self, source_id: str, *, superseded_by: str, observed_at: datetime
    ) -> int: ...  # chunks tombstoned: valid_to and superseded_by set

    async def search(
        self, vector: list[float], limit: int, as_of: datetime | None = None, project_id: str | None = None
    ) -> list[ChunkHit]: ...


class GraphStore(Protocol):
    async def ensure(self) -> None: ...

    async def known_chunk_keys(self, source_id: str) -> set[str]: ...

    async def apply_revision(
        self,
        source: SourceRevision,
        *,
        added: dict[str, GraphExtraction],
        removed: set[str],
        kept: set[str],
        observed_at: datetime,
    ) -> RevisionResult: ...

    async def delete_source(self, source_id: str, *, observed_at: datetime) -> DeleteResult: ...

    async def neighborhoods(
        self, terms: list[str], limit: int = 10, as_of: datetime | None = None
    ) -> list[GraphFact]: ...


class DocumentStore(Protocol):
    async def ensure(self) -> None: ...

    async def put(self, spec_id: str, *, title: str, content: str, project_id: str = "Personal-KB") -> None: ...

    async def get(self, spec_id: str) -> SpecDocument | None: ...

    async def all(self) -> list[SpecDocument]: ...

    async def delete(self, spec_id: str) -> None: ...
