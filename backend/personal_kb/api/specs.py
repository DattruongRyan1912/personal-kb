import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from personal_kb.core.auth import current_user
from personal_kb.services.chunking import SpecChunk, parse_frontmatter
from personal_kb.services.memory_ports import DocumentStore

router = APIRouter(prefix="/api/v1/specs", tags=["specs"], dependencies=[Depends(current_user)])

SpecId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
DEFAULT_STATUS = SpecChunk.model_fields["status"].default  # ingestion's status when the frontmatter has none


class SpecCard(BaseModel):
    spec_id: str
    title: str
    owner: str | None
    status: str


class SpecContentResponse(BaseModel):
    spec_id: str
    title: str
    owner: str | None
    status: str
    content: str
    content_hash: str  # SHA-256 digest


def get_documents(request: Request) -> DocumentStore:
    return request.app.state.tool_context.documents


@router.get("/{spec_id}", responses={404: {"description": "no spec with this id"}})
async def spec_card(spec_id: SpecId, documents: Annotated[DocumentStore, Depends(get_documents)]) -> SpecCard:
    doc = await documents.get(spec_id)
    if doc is None:
        return JSONResponse(status_code=404, content={"error": "SPEC_NOT_FOUND", "message": f"no spec {spec_id}"})
    meta, _ = parse_frontmatter(doc.content)
    owner = meta.get("owner") or meta.get("author")
    return SpecCard(
        spec_id=doc.spec_id,
        title=doc.title or spec_id,
        owner=str(owner) if owner else None,
        status=str(meta.get("status") or DEFAULT_STATUS),
    )


@router.get("/{spec_id}/content", responses={404: {"description": "no spec with this id"}})
async def spec_content(
    spec_id: SpecId, documents: Annotated[DocumentStore, Depends(get_documents)]
) -> SpecContentResponse:
    doc = await documents.get(spec_id)
    if doc is None:
        return JSONResponse(status_code=404, content={"error": "SPEC_NOT_FOUND", "message": f"no spec {spec_id}"})
    meta, _ = parse_frontmatter(doc.content)
    owner = meta.get("owner") or meta.get("author")
    content_hash = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()
    return SpecContentResponse(
        spec_id=doc.spec_id,
        title=doc.title or spec_id,
        owner=str(owner) if owner else None,
        status=str(meta.get("status") or DEFAULT_STATUS),
        content=doc.content,
        content_hash=content_hash,
    )
