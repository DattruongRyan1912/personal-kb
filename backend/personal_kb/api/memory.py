"""Memory search: the "brain interface" agents and users query (issue 1.4)."""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime, BaseModel, StringConstraints

from personal_kb.core.auth import current_user
from personal_kb.services.retrieval import HybridRetriever, SearchResult

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/memory", tags=["memory"], dependencies=[Depends(current_user)])


class SearchRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    as_of: AwareDatetime | None = None  # answer from what was valid then (PoC-A); a time needs its offset


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    took_ms: int


def get_retriever(request: Request) -> HybridRetriever:
    return request.app.state.retriever


@router.post("/search")
async def search(body: SearchRequest, retriever: Annotated[HybridRetriever, Depends(get_retriever)]) -> SearchResponse:
    started = time.perf_counter()
    results = await retriever.search(body.query, as_of=body.as_of)
    took_ms = round((time.perf_counter() - started) * 1000)
    log.info("[memory.search] %d results in %d ms", len(results), took_ms)
    return SearchResponse(query=body.query, results=results, took_ms=took_ms)
