"""Liveness for container healthchecks (issue 4.3): the process answers. No token, and no dependency is checked:
a database that is down makes requests fail with 503, it does not make the container unhealthy."""

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
