"""Agent Protocol endpoints: Machine-to-Machine (M2M) interface for AI Agents.

Provides structured, deterministic, machine-readable JSON endpoints for querying,
searching, and retrieving specifications without conversational filler or SSE.
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from personal_kb.core.auth import AuthenticationError, CurrentUser
from personal_kb.services.agent import ChatAgent
from personal_kb.services.chunking import parse_frontmatter
from personal_kb.services.citations import cited_spec_ids
from personal_kb.services.memory_ports import DocumentStore
from personal_kb.services.retrieval import HybridRetriever, SearchResult
from personal_kb.tools.base import ToolContext

log = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


async def agent_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    x_agent_key: Annotated[str | None, Header(alias="X-Agent-Key")] = None,
) -> CurrentUser:
    """Authenticate agent requests via DEV_LOGIN, X-Agent-Key, or Bearer token."""
    settings = request.app.state.settings
    if settings.dev_login:
        return CurrentUser(id="dev-agent", email="agent@cyberos.local")

    if settings.agent_api_key and x_agent_key == settings.agent_api_key.get_secret_value():
        return CurrentUser(id="m2m-agent", email="agent@cyberos.local")

    if credentials is not None:
        return await request.app.state.auth.verify(credentials.credentials)

    raise AuthenticationError("Agent authentication required: provide valid Bearer token or X-Agent-Key header")


router = APIRouter(prefix="/api/v1/agent", tags=["agent-protocol"], dependencies=[Depends(agent_auth)])


def get_retriever(request: Request) -> HybridRetriever:
    return request.app.state.retriever


def get_documents(request: Request) -> DocumentStore:
    return request.app.state.tool_context.documents


def get_tool_context(
    retriever: Annotated[HybridRetriever, Depends(get_retriever)],
    documents: Annotated[DocumentStore, Depends(get_documents)],
) -> ToolContext:
    return ToolContext(retriever=retriever, documents=documents)


def get_agent(request: Request) -> ChatAgent:
    return request.app.state.agent


class AgentSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="Nội dung tìm kiếm ngữ nghĩa")
    limit: int = Field(default=5, ge=1, le=50, description="Số lượng kết quả trả về")


class AgentSearchResponse(BaseModel):
    query: str
    total: int
    took_ms: int
    results: list[SearchResult]


class SpecSummary(BaseModel):
    spec_id: str
    title: str
    owner: str | None
    status: str


class SpecCatalogueResponse(BaseModel):
    total: int
    specs: list[SpecSummary]


class SpecDetailResponse(BaseModel):
    spec_id: str
    title: str
    owner: str | None
    status: str
    content: str


class AgentQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000, description="Câu hỏi dành cho trợ lý tri thức")
    session_id: str | None = Field(default=None, description="Tùy chọn session_id nếu muốn giữ ngữ cảnh")


class AgentQueryResponse(BaseModel):
    query: str
    answer: str
    sources: list[str]
    took_ms: int


@router.post("/tools/search", response_model=AgentSearchResponse)
async def agent_search(
    body: AgentSearchRequest,
    retriever: Annotated[HybridRetriever, Depends(get_retriever)],
) -> AgentSearchResponse:
    """Tool: Search knowledge base semantically and relationally, returning raw scored chunks."""
    started = time.perf_counter()
    results = await retriever.search(body.query)
    took_ms = round((time.perf_counter() - started) * 1000)
    trimmed = results[: body.limit]
    return AgentSearchResponse(query=body.query, total=len(trimmed), took_ms=took_ms, results=trimmed)


@router.get("/tools/specs", response_model=SpecCatalogueResponse)
async def agent_list_specs(
    documents: Annotated[DocumentStore, Depends(get_documents)],
) -> SpecCatalogueResponse:
    """Tool: List all spec documents with metadata catalog."""
    docs = await documents.all()
    summaries: list[SpecSummary] = []
    for doc in docs:
        meta, _ = parse_frontmatter(doc.content)
        owner = meta.get("owner") or meta.get("author")
        status = meta.get("status") or "active"
        summaries.append(
            SpecSummary(
                spec_id=doc.spec_id,
                title=doc.title or doc.spec_id,
                owner=str(owner) if owner else None,
                status=str(status),
            )
        )
    return SpecCatalogueResponse(total=len(summaries), specs=summaries)


@router.get("/tools/specs/{spec_id}", response_model=SpecDetailResponse)
async def agent_get_spec(
    spec_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_.-]{1,64}$")],
    documents: Annotated[DocumentStore, Depends(get_documents)],
) -> SpecDetailResponse | JSONResponse:
    """Tool: Retrieve full markdown text and metadata of a specific spec document."""
    doc = await documents.get(spec_id)
    if doc is None:
        return JSONResponse(
            status_code=404,
            content={"error": "SPEC_NOT_FOUND", "message": f"Spec {spec_id} not found"},
        )
    meta, _ = parse_frontmatter(doc.content)
    owner = meta.get("owner") or meta.get("author")
    status = meta.get("status") or "active"
    return SpecDetailResponse(
        spec_id=doc.spec_id,
        title=doc.title or doc.spec_id,
        owner=str(owner) if owner else None,
        status=str(status),
        content=doc.content,
    )


@router.post("/query", response_model=AgentQueryResponse)
async def agent_query(
    body: AgentQueryRequest,
    tool_context: Annotated[ToolContext, Depends(get_tool_context)],
    agent: Annotated[ChatAgent, Depends(get_agent)],
    user: Annotated[CurrentUser, Depends(agent_auth)],
) -> AgentQueryResponse:
    """Non-streaming, structured query endpoint for AI Agents."""
    started = time.perf_counter()
    session_id = body.session_id or f"agent-{int(time.time())}"

    # ChatAgent.ask takes (user_id, session_id, text, tool_context) and returns AIMessage
    answer_msg = await agent.ask(user.id, session_id, body.query, tool_context)
    took_ms = round((time.perf_counter() - started) * 1000)

    content = str(answer_msg.content)
    sources = cited_spec_ids(content)
    return AgentQueryResponse(query=body.query, answer=content, sources=sources, took_ms=took_ms)
