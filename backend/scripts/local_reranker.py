"""Development re-ranker on the Mac's GPU, with the same /rerank API as Text Embeddings Inference (issue 1.4).

BAAI/bge-reranker-v2-m3 on CPU in Docker takes about 4 s per pair (107 s for 25 passages), far from the < 2 s target,
so during development it runs natively through FlagEmbedding on Apple's GPU (MPS) instead. The api reaches it through
RERANKER_URL / RERANKER_URL_DOCKER; TeiReranker does not change. Which re-ranker production uses is Stephen's call.

Usage, from ai/backend (the first start downloads the model, about 2.2 GB):
  uv run --group local-reranker python -m scripts.local_reranker [--port 8081]
"""

import argparse
import asyncio
from collections.abc import Callable, Sequence

from fastapi import FastAPI
from pydantic import BaseModel

Scorer = Callable[[Sequence[tuple[str, str]]], list[float]]

MODEL = "BAAI/bge-reranker-v2-m3"


class RerankRequest(BaseModel):
    query: str
    texts: list[str]
    raw_scores: bool = False  # accepted for TEI compatibility; scores are always normalized to 0-1
    truncate: bool = True


class RerankScore(BaseModel):
    index: int
    score: float


def create_app(score: Scorer) -> FastAPI:
    app = FastAPI(title="Local re-ranker (TEI-compatible)")
    # one scoring at a time: the model on the GPU (MPS) is not thread-safe, two at once crashed one with a 500
    scoring = asyncio.Lock()

    @app.post("/rerank")
    async def rerank(body: RerankRequest) -> list[RerankScore]:
        if not body.texts:
            return []
        async with scoring:
            scores = await asyncio.to_thread(score, [(body.query, text) for text in body.texts])
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return [RerankScore(index=i, score=s) for i, s in ranked]

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


def flag_scorer(model: str = MODEL, max_length: int = 512) -> Scorer:
    """FlagEmbedding cross-encoder; picks the GPU (MPS) when available, fp16, sigmoid-normalized scores."""
    from FlagEmbedding import FlagReranker  # heavy (torch): only in the local-reranker dependency group

    reranker = FlagReranker(model, use_fp16=True)

    def score(pairs: Sequence[tuple[str, str]]) -> list[float]:
        # batch 4, 512 tokens: fastest on MPS (25 pairs ~1.7 s warm; bigger batches pad every pair to the longest)
        result = reranker.compute_score([list(p) for p in pairs], normalize=True, max_length=max_length, batch_size=4)
        return [float(s) for s in (result if isinstance(result, list) else [result])]

    return score


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # Docker Desktop reaches the host's 127.0.0.1 through host.docker.internal: nothing needs the LAN
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--max-length", type=int, default=512, help="tokens read per query+passage pair")
    return parser.parse_args(argv)


if __name__ == "__main__":
    import uvicorn

    args = parse_args()
    uvicorn.run(create_app(flag_scorer(args.model, args.max_length)), host=args.host, port=args.port)
