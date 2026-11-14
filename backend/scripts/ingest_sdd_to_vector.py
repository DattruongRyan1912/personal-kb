"""Ingest SDD Markdown files into the vector store, keeping their history (issue 1.2, PoC-A/A2 #297).

Usage (SOURCE_DIR defaults to mock_data):
  in the ai-backend container:  docker compose exec ai-backend python -m scripts.ingest_sdd_to_vector [SOURCE_DIR]
  from ai/backend:       uv run --env-file ../.env python -m scripts.ingest_sdd_to_vector [SOURCE_DIR]
  forget a spec, past included:  ... -m scripts.ingest_sdd_to_vector --delete SPC-5
Running it again is safe: only changed chunks are embedded; removed chunks are closed, not deleted (questions about the
past still find them). The store is Postgres + pgvector.
"""

import argparse
import asyncio
import logging
import time
from pathlib import Path

from personal_kb.core.config import get_settings
from personal_kb.infrastructure.memory_backend import build_memory
from personal_kb.infrastructure.openai_client import build_embedding_client
from personal_kb.services.embedding import EmbeddingService
from personal_kb.services.ingestion import ingest_documents

log = logging.getLogger("ingest")


async def main(paths: list[Path], delete: list[str]) -> None:
    settings = get_settings()
    embedding_client = build_embedding_client(settings)
    embedder = EmbeddingService(
        embedding_client, model=settings.embedding_model, dimensions=settings.embedding_dimensions
    )
    started = time.perf_counter()
    try:
        async with build_memory(settings) as stores:
            await stores.vectors.ensure()
            await stores.documents.ensure()
            for spec_id in delete:
                removed = await stores.vectors.delete_source(spec_id)
                await stores.documents.delete(spec_id)
                log.info("%s deleted: %d chunks", spec_id, removed)
            if paths:
                report = await ingest_documents(
                    paths, embedder=embedder, vectors=stores.vectors, documents=stores.documents
                )
                log.info(
                    "ingested %d documents, %d chunks (%d embedded, %d closed) in %.1fs into %s",
                    report.documents,
                    report.chunks,
                    report.added,
                    report.closed,
                    time.perf_counter() - started,
                    "postgres",
                )
    finally:
        await embedding_client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--delete", action="append", default=[], metavar="SPEC_ID")
    args = parser.parse_args()
    source = args.source or (None if args.delete else Path("mock_data"))
    markdown_files = (
        sorted(
            [
                p
                for p in source.rglob("*.md")
                if p.is_file() and not p.name.startswith(".") and "proposals" not in p.parts
            ]
        )
        if source
        else []
    )
    if source and not markdown_files:
        raise SystemExit(f"no Markdown files in {source}")
    asyncio.run(main(markdown_files, args.delete))
