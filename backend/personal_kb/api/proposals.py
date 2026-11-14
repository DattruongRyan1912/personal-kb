"""API router for Knowledge Base proposals and governance (issue: Knowledge Approval)."""

import json
import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from personal_kb.core.auth import current_user
from personal_kb.services.proposals import (
    DuplicateProposalError,
    KbProposal,
    ProposalConflictError,
    ProposalNotFoundError,
    ProposalStore,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"], dependencies=[Depends(current_user)])


def get_proposal_store(request: Request) -> ProposalStore:
    if not hasattr(request.app.state, "proposals"):
        request.app.state.proposals = ProposalStore()
    return request.app.state.proposals


class CreateProposalRequest(BaseModel):
    spec_id: str = Field(..., pattern=r"^[A-Za-z0-9_.-]{1,64}$", description="Mã Spec tài liệu")
    title: str = Field(..., min_length=1, max_length=200, description="Tiêu đề đề xuất")
    action: Literal["UPDATE_SECTION", "CREATE_DOCUMENT", "REPLACE_DOCUMENT"] = "UPDATE_SECTION"
    section: str = Field(default="", max_length=200, description="Tiêu đề mục (heading) cần sửa hoặc thêm")
    proposed_content: str = Field(..., min_length=1, description="Nội dung Markdown mới")
    rationale: str = Field(..., min_length=1, description="Lý do đề xuất cập nhật")


class ApproveProposalRequest(BaseModel):
    reviewer: str = Field(default="Admin", min_length=1, max_length=100)
    force: bool = False


class RejectProposalRequest(BaseModel):
    reviewer: str = Field(default="Admin", min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=1000)


@router.get("", response_model=list[KbProposal])
async def list_proposals(
    status: Literal["PENDING", "APPROVED", "REJECTED"] | None = Query(None, description="Lọc theo trạng thái"),
    store: ProposalStore = Depends(get_proposal_store),
) -> list[KbProposal]:
    """Danh sách các đề xuất tri thức trong hệ thống."""
    return store.list_all(status=status)


@router.get("/{proposal_id}", response_model=KbProposal)
async def get_proposal(
    proposal_id: str,
    store: ProposalStore = Depends(get_proposal_store),
) -> KbProposal:
    """Xem chi tiết một đề xuất theo ID."""
    prop = store.get(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy đề xuất {proposal_id}")
    return prop


@router.post("", response_model=KbProposal, status_code=201)
async def create_proposal(
    payload: CreateProposalRequest,
    store: ProposalStore = Depends(get_proposal_store),
) -> KbProposal:
    """Tạo đề xuất cập nhật tài liệu mới (ở trạng thái PENDING)."""
    try:
        return store.create(
            spec_id=payload.spec_id,
            title=payload.title,
            action=payload.action,
            section=payload.section,
            proposed_content=payload.proposed_content,
            rationale=payload.rationale,
        )
    except DuplicateProposalError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{proposal_id}/approve", response_model=KbProposal)
async def approve_proposal(
    proposal_id: str,
    payload: ApproveProposalRequest,
    request: Request,
    store: ProposalStore = Depends(get_proposal_store),
) -> KbProposal:
    """Phê duyệt đề xuất: Ghi đè spec markdown, re-ingest vào DocumentStore và vector store."""
    stores = getattr(request.app.state, "stores", None)
    retriever = getattr(request.app.state, "retriever", None)

    vectors = getattr(stores, "vectors", None) if stores else None
    documents = getattr(stores, "documents", None) if stores else None
    embedder = getattr(retriever, "embedder", None) if retriever else None

    # Nếu đang chạy môi trường đầy đủ có memory stores
    if embedder is not None and vectors is not None and documents is not None:
        try:
            approved_prop = await store.approve(
                proposal_id,
                reviewer=payload.reviewer,
                embedder=embedder,
                vectors=vectors,
                documents=documents,
                force=payload.force,
            )
            cache = getattr(request.app.state, "cache", None)
            if cache is not None:
                target_project = getattr(approved_prop, "project_id", "Personal-KB")
                await cache.bump_version(target_project)
            return approved_prop
        except ProposalNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ProposalConflictError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # Fallback nếu chạy test hoặc môi trường không có vector backend
    prop = store.get(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy đề xuất {proposal_id}")
    if prop.status != "PENDING":
        raise HTTPException(status_code=400, detail=f"Đề xuất {proposal_id} đã ở trạng thái {prop.status}")

    # Anti-Collision Negative Constraint check
    if not payload.force and prop.conflict_detected:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Không thể phê duyệt: Đề xuất vi phạm Negative Constraint [{prop.conflict_rule_id}]: "
                f"{prop.conflict_reason}. Yêu cầu bật cờ force=True để ghi đè quy chuẩn."
            ),
        )

    prop.status = "APPROVED"
    prop.reviewed_at = datetime.now(UTC).isoformat()
    prop.reviewed_by = payload.reviewer
    path = store._proposal_path(proposal_id)
    path.write_text(json.dumps(prop.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    cache = getattr(request.app.state, "cache", None)
    if cache is not None:
        target_project = getattr(prop, "project_id", "Personal-KB")
        await cache.bump_version(target_project)
    return prop


@router.post("/{proposal_id}/reject", response_model=KbProposal)
async def reject_proposal(
    proposal_id: str,
    payload: RejectProposalRequest,
    store: ProposalStore = Depends(get_proposal_store),
) -> KbProposal:
    """Từ chối đề xuất cập nhật tri thức kèm lý do ghi chú."""
    try:
        return store.reject(proposal_id, reviewer=payload.reviewer, note=payload.note)
    except ProposalNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except DuplicateProposalError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
