"""Command Line Interface for Personal-KB.

Provides developer and agent utility commands such as code graph indexing,
telemetry inspection, and knowledge management.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from personal_kb.services.code_graph_indexer import CodeGraphIndexer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("personal_kb.cli")


def cmd_index_code(args: argparse.Namespace) -> int:
    """Index source code using native Tree-sitter AST parser into CodeGraph SQLite."""
    target_path = Path(args.target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        log.error("Target directory does not exist or is not a directory: %s", target_path)
        return 1

    if not args.quiet:
        log.info("Starting CodeGraph Indexing on %s (force=%s)...", target_path, args.force)

    start_ts = time.time()
    try:
        indexer = CodeGraphIndexer(target_path)
        result = indexer.index(force=args.force)
    except Exception as e:
        log.exception("Indexing failed with error: %s", e)
        return 2

    elapsed = round(time.time() - start_ts, 3)

    if args.json:
        sys.stdout.write(json.dumps(result.to_dict(), indent=2) + "\n")
        return 0

    if not args.quiet:
        log.info("Indexing completed in %ss", elapsed)
        log.info("  DB Path:        %s", result.db_path)
        log.info("  DB Size:        %.2f MB", result.db_size_bytes / (1024 * 1024))
        log.info("  Files Indexed:  %d", result.files_indexed)
        log.info("  Files Skipped:  %d", result.files_skipped)
        log.info("  Files Deleted:  %d", result.files_deleted)
        log.info("  Nodes Created:  %d", result.nodes_count)
        log.info("  Edges Linked:   %d", result.edges_count)
        if result.errors:
            log.warning("  Errors (%d):", len(result.errors))
            for err in result.errors[:5]:
                log.warning("    - %s", err)
            if len(result.errors) > 5:
                log.warning("    ... and %d more", len(result.errors) - 5)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="personal-kb",
        description="Personal-KB CLI: Core Knowledge Fabric & Code Intelligence",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # index-code
    p_index = subparsers.add_parser("index-code", help="Index codebase with native Tree-sitter")
    p_index.add_argument("target_dir", nargs="?", default=".", help="Target project root directory")
    p_index.add_argument("--force", action="store_true", help="Force full re-index, clearing cache")
    p_index.add_argument("--quiet", action="store_true", help="Quiet output (minimal logging)")
    p_index.add_argument("--json", action="store_true", help="Output results in JSON format")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "index-code":
        return cmd_index_code(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
