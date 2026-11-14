"""Worklog REST route: read recent entries for a session brief, and write entries."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from personal_kb.api.agent import agent_auth
from personal_kb.services.worklog import (
    WORKLOG_KINDS,
    NewWorklogEntry,
    WorklogEntry,
    WorklogStore,
    WorklogValidationError,
    validate_entry,
)

router = APIRouter(prefix="/api/v1/agent/worklog", tags=["worklog"], dependencies=[Depends(agent_auth)])


def get_worklog_store(request: Request) -> WorklogStore:
    store = request.app.state.tool_context.worklog
    if store is None:
        raise HTTPException(status_code=503, detail="Worklog store không khả dụng trên backend này")
    return store


def get_worklog_projects(request: Request) -> frozenset[str]:
    return request.app.state.tool_context.projects


class WorklogEntryIn(BaseModel):
    project: str
    kind: str
    summary: str
    next_steps: str = ""
    agent: str = ""
    session_id: str = ""
    branch: str = ""


class WorklogEntryOut(WorklogEntryIn):
    id: int
    created_at: str


def _out(entry: WorklogEntry) -> WorklogEntryOut:
    data = asdict(entry)
    data["created_at"] = entry.created_at.isoformat()
    return WorklogEntryOut(**data)


@router.get("", response_model=list[WorklogEntryOut])
async def list_worklog(
    project: str,
    store: Annotated[WorklogStore, Depends(get_worklog_store)],
    projects: Annotated[frozenset[str], Depends(get_worklog_projects)],
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    kind: str = "",
) -> list[WorklogEntryOut]:
    if project not in projects:
        raise HTTPException(status_code=422, detail=f"project không hợp lệ: '{project}' không có trong danh sách dự án")
    if kind and kind not in WORKLOG_KINDS:
        raise HTTPException(status_code=422, detail=f"kind phải là một trong: {', '.join(WORKLOG_KINDS)}")
    return [_out(e) for e in await store.recent(project, limit=limit, kind=kind)]


@router.post("", response_model=WorklogEntryOut, status_code=201)
async def add_worklog(
    body: WorklogEntryIn,
    store: Annotated[WorklogStore, Depends(get_worklog_store)],
    projects: Annotated[frozenset[str], Depends(get_worklog_projects)],
) -> WorklogEntryOut:
    try:
        entry = validate_entry(NewWorklogEntry(**body.model_dump()), projects)
    except WorklogValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _out(await store.add(entry))
