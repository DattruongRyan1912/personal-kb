"""Internal system endpoints."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from personal_kb.core.auth import current_user
from personal_kb.infrastructure.memory_backend import MemoryStores

router = APIRouter(prefix="/api/v1/system", tags=["system"], dependencies=[Depends(current_user)])


class InitDbResponse(BaseModel):
    backend: str  # always "postgres" (decision B4); kept for the API's shape
    collection: str  # where the chunks are: <schema>.chunks
    created: bool


@router.post("/init-db")
async def init_db(request: Request) -> InitDbResponse:
    """Create what the memory needs (chunks, documents, graph constraints); safe to run again."""
    settings = request.app.state.settings
    stores: MemoryStores = request.app.state.stores
    created = await stores.vectors.ensure()
    await stores.documents.ensure()
    await stores.graph.ensure()
    return InitDbResponse(backend="postgres", collection=f"{settings.postgres_schema}.chunks", created=created)
