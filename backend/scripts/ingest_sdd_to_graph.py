"""Extract a knowledge graph from SDD Markdown files into the graph store, keeping its history (issue 1.3, PoC-A/A2).

Usage (PATH is a Markdown file or a directory of them; default: mock_data):
  in the ai-backend container:  docker compose exec ai-backend python -m scripts.ingest_sdd_to_graph [PATH ...]
  from ai/backend:       uv run --env-file ../.env python -m scripts.ingest_sdd_to_graph [PATH ...]
  forget a spec and every fact only it stated:  ... -m scripts.ingest_sdd_to_graph --delete SPC-5
Running it again is safe: only chunks that changed go to the model, and the facts of removed chunks are closed (kept
for questions about the past). A spec whose model call still fails after the retries (a timeout, the model down) is
not applied at all and the others go on; the run then exits 1 naming it, so run again. So is a spec another run
applied meanwhile (Postgres refuses a revision planned from chunk keys that changed). The store is Postgres.
"""

import argparse
import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from personal_kb.core.config import get_settings
from personal_kb.core.prompts import load_prompt
from personal_kb.infrastructure.memory_backend import build_memory
from personal_kb.infrastructure.openai_client import build_openai_client
from personal_kb.services.graph_extraction import GraphExtractor
from personal_kb.services.graph_ingestion import ingest_graph_revision
from personal_kb.services.ingestion import load_source
from personal_kb.services.memory_ports import StaleRevisionError
from personal_kb.services.openai_retry import is_transient

log = logging.getLogger("ingest_graph")


async def ingest_paths(paths: list[Path], *, extractor, store, now: datetime) -> list[str]:
    """Each spec's revision in turn; returns the specs left unapplied because the model failed transiently."""
    deferred = []
    for path in paths:
        source, chunks = load_source(path)
        started = time.perf_counter()
        try:
            report = await ingest_graph_revision(source, chunks, extractor=extractor, store=store, observed_at=now)
        except Exception as exc:
            if not (is_transient(exc) or isinstance(exc, StaleRevisionError)):
                raise
            log.warning("%s not applied (%s): run again", source.source_id, type(exc).__name__)
            deferred.append(source.source_id)
            continue
        log.info(
            "%s (%s): %d chunks, %d extracted, %d skipped, %d kept, %d removed; "
            "relationships %d opened, %d closed, in %.1fs",
            source.source_id,
            source.revision,
            report.chunks,
            report.extracted,
            report.skipped,
            report.kept,
            report.removed,
            report.opened,
            report.closed,
            time.perf_counter() - started,
        )
    return deferred


async def main(paths: list[Path], delete: list[str], drop_legacy: bool) -> list[str]:
    settings = get_settings()
    openai_client = build_openai_client(settings)
    extractor = GraphExtractor(
        openai_client,
        model=settings.llm_model,
        prompt=load_prompt("graph_extraction"),
        reasoning_effort=settings.llm_reasoning_effort,
    )
    now = datetime.now(UTC)
    try:
        async with build_memory(settings) as stores:
            store = stores.graph
            await store.ensure()
            if drop_legacy:
                log.warning("--drop-legacy ignored: the Postgres graph has no facts written before PoC-A")
            for spec_id in delete:
                result = await store.delete_source(spec_id, observed_at=now)
                log.info(
                    "%s deleted: %d relationships and %d nodes purged", spec_id, result.relationships, result.nodes
                )
            return await ingest_paths(paths, extractor=extractor, store=store, now=now)
    finally:
        await openai_client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--delete", action="append", default=[], metavar="SPEC_ID")
    parser.add_argument("--drop-legacy", action="store_true")
    args = parser.parse_args()
    paths = args.paths or ([] if args.delete or args.drop_legacy else [Path("mock_data")])
    markdown_files = sorted({f for p in paths for f in (p.glob("*.md") if p.is_dir() else [p])})
    if not markdown_files and not args.delete and not args.drop_legacy:
        raise SystemExit("no Markdown files given")
    deferred = asyncio.run(main(markdown_files, args.delete, args.drop_legacy))
    if deferred:
        raise SystemExit(f"not applied, run again: {', '.join(deferred)}")
