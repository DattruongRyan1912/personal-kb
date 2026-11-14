"""Search quality on a fixed set of questions: hit@5 and MRR against the live stores (docs/search-eval/).

The expected spec of each case is the one whose section answers the question, decided by reading it, never by
counting keywords (that would grade a keyword search against itself). Off-topic cases expect nothing back.

Usage, inside kb-backend:
  python -m scripts.eval_search [--cases scripts/search_cases.json] [--json out.json]
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from personal_kb.bootstrap import services
from personal_kb.core.config import get_settings

K = 5
CASES = Path(__file__).with_name("search_cases.json")


def hit_at(ids: list[str], want: list[str], k: int) -> bool:
    """A wanted spec in the first k; for an off-topic case (want empty), nothing returned."""
    return not ids if not want else any(i in want for i in ids[:k])


def reciprocal_rank(ids: list[str], want: list[str]) -> float:
    if not want:
        return 0.0 if ids else 1.0
    return next((1 / rank for rank, i in enumerate(ids, 1) if i in want), 0.0)


async def evaluate(cases: list[dict]) -> list[dict]:
    async with services(get_settings()) as built:
        rows = []
        for case in cases:
            results = await built.tool_context.retriever.search(case["query"], project_id=case["project"], cached=False)
            ids = list(dict.fromkeys(i for r in results for i in r.spec_ids))
            rows.append(
                case | {"ids": ids, "hit": hit_at(ids, case["want"], K), "rr": reciprocal_rank(ids, case["want"])}
            )
        return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    logging.disable(logging.WARNING)
    rows = asyncio.run(evaluate(json.loads(args.cases.read_text(encoding="utf-8"))))
    for r in rows:
        verdict = "HIT " if r["hit"] else "MISS"
        print(f"{verdict} [{r['kind']}] {r['query']} ({r['project']}) want {r['want']} got {r['ids'][:K]}")
    hits, mrr = sum(r["hit"] for r in rows), sum(r["rr"] for r in rows) / len(rows)
    print(f"HIT@{K} {hits}/{len(rows)}  MRR {mrr:.2f}")
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
