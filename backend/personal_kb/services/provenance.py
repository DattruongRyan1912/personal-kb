"""Where a fact comes from and when it holds (PoC-A, #297).

A spec is a source. Each of its chunks is keyed by a hash of its headings and content, so a chunk that did not change
between two revisions keeps its key, its vectors and its graph facts and is never sent to a model again; only new keys
are embedded and extracted, and only removed keys are closed. The graph is extracted by an LLM, and an unchanged chunk
is never asked again, so "the model did not say it this time" cannot close its facts. An edited chunk is a new key,
read from scratch: a fact its old version stated and the model does not repeat closes. When the model answers the new
key invalidly, the old key still closes (the new key is retried on the next run): keeping it open would block the
spec's retractions for good, since some chunks always fail. A failed request applies nothing (graph_ingestion.py).
"""

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from personal_kb.services.chunking import SpecChunk


def chunk_key(chunk: SpecChunk) -> str:
    text = "\n".join([*chunk.headings, chunk.content])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def keyed_chunks(chunks: Sequence[SpecChunk]) -> list[tuple[str, SpecChunk]]:
    """Each chunk with its key; identical chunks of one spec get -0, -1… so no two share a key."""
    seen: Counter[str] = Counter()
    keyed = []
    for chunk in chunks:
        base = chunk_key(chunk)
        keyed.append((f"{base}-{seen[base]}", chunk))
        seen[base] += 1
    return keyed


def assertion(source_id: str, key: str) -> str:
    return f"{source_id}#{key}"


@dataclass(frozen=True)
class SourceRevision:
    source_id: str
    revision: str  # the frontmatter's `version`, else "sha-" and the first 12 hex digits of the file's hash
    content_hash: str  # sha256 of the whole file


def source_revision(source_id: str, text: str, meta: dict) -> SourceRevision:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    version = meta.get("version")
    return SourceRevision(source_id, str(version) if version is not None else f"sha-{digest[:12]}", digest)


@dataclass(frozen=True)
class RevisionPlan:
    added: list[tuple[str, SpecChunk]]  # keys the store does not hold yet: only these are embedded or extracted
    removed: set[str]  # keys the store holds that this revision no longer has: their facts are closed
    kept: set[str]


def plan_revision(known: set[str], keyed: Sequence[tuple[str, SpecChunk]]) -> RevisionPlan:
    current = {key for key, _ in keyed}
    return RevisionPlan(
        added=[(key, chunk) for key, chunk in keyed if key not in known],
        removed=known - current,
        kept=known & current,
    )
