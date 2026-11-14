"""Proposal Service: Staging layer and Human Gate for Knowledge Base updates.

Prevents prompt injection, data poisoning, and hallucination cascade by ensuring
agents can only propose updates, while humans retain final approval authority.
Features Optimistic Concurrency Control (OCC) to prevent lost updates and path
traversal protection.
"""

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from personal_kb.services.anti_collision import ConflictCheckResult, detect_conflicts
from personal_kb.services.chunking import parse_frontmatter
from personal_kb.services.ingestion import ingest_documents
from personal_kb.services.knowledge_files import find_spec_file
from personal_kb.services.memory_ports import DocumentStore, VectorStore
from personal_kb.services.projects import project_of

log = logging.getLogger(__name__)

SPEC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class ProposalConflictError(Exception):
    """Raised when the base document has changed since the proposal was created (OCC)."""


class ProposalNotFoundError(Exception):
    """Raised when a proposal ID does not exist."""


class DuplicateProposalError(Exception):
    """Raised when an identical proposal is already pending, already approved, or already in the document."""


class KbProposal(BaseModel):
    id: str
    spec_id: str
    title: str
    action: Literal["UPDATE_SECTION", "CREATE_DOCUMENT", "REPLACE_DOCUMENT"] = "UPDATE_SECTION"
    section: str = Field(description="Target section / heading being updated or added")
    proposed_content: str = Field(description="New markdown content for the section or document")
    rationale: str = Field(description="Explanation of why this proposal was created")
    base_hash: str | None = Field(default=None, description="SHA-256 of the original file when proposed (OCC)")
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    supersedes_spec_id: str | None = Field(
        default=None, description="Mã spec cũ cần tombstone khi đề xuất này được duyệt"
    )
    conflict_detected: bool = Field(default=False, description="Cờ cảnh báo xung đột với Negative Constraints")
    conflict_rule_id: str | None = Field(default=None, description="Mã quy chuẩn bị vi phạm (VD: NC-HR-001)")
    conflict_reason: str | None = Field(default=None, description="Chi tiết lý do cảnh báo xung đột")
    created_at: str
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None

    @property
    def project_id(self) -> str:
        """The project of the target spec, by its id (whose semantic cache an approval invalidates)."""
        return project_of(self.spec_id)


def resolve_spec_path(knowledge_dir: Path, spec_id: str) -> Path:
    """Safely resolve spec markdown file path, preventing Path Traversal."""
    if not SPEC_ID_PATTERN.match(spec_id):
        raise ValueError(
            f"Invalid spec_id format: '{spec_id}'. Allowed characters: letters, digits, _, -, . (1-64 chars)"
        )

    # by file name or frontmatter id (KB-01 lives in KB-01-huong-dan.md), as the Data Hub finds it
    found = find_spec_file(knowledge_dir, spec_id)
    if found is not None:
        return found
    direct = (knowledge_dir / f"{spec_id}.md").resolve()
    if not direct.is_relative_to(knowledge_dir.resolve()):
        raise ValueError(f"Security error: Path traversal attempt detected for spec_id '{spec_id}'")
    return direct


def file_hash(path: Path) -> str | None:
    """Calculate SHA-256 hash of a file if it exists."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_to_spec(prop: "KbProposal", spec_file: Path) -> None:
    """Write an approved proposal into its spec file; the store and scripts/manage_proposals.py both use it."""
    if prop.action == "CREATE_DOCUMENT" or not spec_file.is_file():
        spec_file.parent.mkdir(parents=True, exist_ok=True)
        content = f"---\nid: {prop.spec_id}\ntitle: {prop.title}\nstatus: active\n---\n\n{prop.proposed_content}\n"
        spec_file.write_text(content, encoding="utf-8")
    elif prop.action == "REPLACE_DOCUMENT":
        # the stored content is stripped: a Markdown file ends with a newline
        spec_file.write_text(f"{prop.proposed_content}\n", encoding="utf-8")
    else:  # UPDATE_SECTION
        orig_text = spec_file.read_text(encoding="utf-8")
        lines = orig_text.splitlines(keepends=True)
        headings = _heading_lines(lines)
        # the section is the first heading that starts with its name; it runs to the next level 1-3 heading
        start = next((i for i, _, text in headings if text.startswith(prop.section)), None)
        if start is None:
            new_text = f"{orig_text.rstrip()}\n\n## {prop.section}\n\n{prop.proposed_content}\n"
        else:
            end = next((i for i, level, _ in headings if i > start and level <= 3), None)
            rest = "\n" + "".join(lines[end:]) if end is not None else ""
            new_text = f"{''.join(lines[:start])}{lines[start].rstrip()}\n\n{prop.proposed_content}\n{rest}"
        spec_file.write_text(new_text, encoding="utf-8")


_HEADING = re.compile(r"(#{1,6}) (.*)")
_FENCE = re.compile(r" {0,3}(```|~~~)")


def _heading_lines(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line index, level, text) of every Markdown heading outside fenced code blocks."""
    found, fence = [], None
    for i, line in enumerate(lines):
        if m := _FENCE.match(line):
            fence = None if fence == m.group(1) else fence or m.group(1)
        elif fence is None and (h := _HEADING.match(line)):
            found.append((i, len(h.group(1)), h.group(2).strip()))
    return found


class ProposalStore:
    def __init__(self, knowledge_dir: Path | None = None) -> None:
        self.knowledge_dir = knowledge_dir or (
            Path("knowledge") if Path("knowledge").exists() else Path("../knowledge")
        )
        self.proposals_dir = self.knowledge_dir / "proposals"
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self._seed_samples_if_empty()

    def _seed_samples_if_empty(self) -> None:
        if any(self.proposals_dir.glob("PROP-*.json")):
            return
        # Seed 1 Pending Proposal
        p1 = KbProposal(
            id="PROP-SEED-001",
            spec_id="HR-M04",
            title="Bổ sung quy định phụ cấp độc hại mức 4",
            action="UPDATE_SECTION",
            section="Chế độ phụ cấp và bảo hộ lao động",
            proposed_content=(
                "### Phụ cấp độc hại mức 4 (Mới đề xuất 2026)\n"
                "- Áp dụng cho nhân sự làm việc trực tiếp tại khu vực nguy cơ cao (phòng sạch, hóa chất đặc thù).\n"
                "- Mức phụ cấp: 1,500,000 VND / tháng, chi trả cùng kỳ lương chính thức.\n"
                "- Yêu cầu kiểm tra sức khỏe định kỳ 6 tháng/lần và trang bị bảo hộ đạt chuẩn an toàn lao động."
            ),
            rationale="Cập nhật theo thông tư an toàn lao động mới và biên bản thống nhất với Ban Nhân sự quý 4/2026.",
            base_hash=None,
            status="PENDING",
            created_at=datetime.now(UTC).isoformat(),
        )
        self._proposal_path(p1.id).write_text(
            json.dumps(p1.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Seed 1 Approved Proposal
        p2 = KbProposal(
            id="PROP-SEED-002",
            spec_id="HR-M01",
            title="Chuẩn hóa định dạng mã nhân viên 6 chữ số",
            action="UPDATE_SECTION",
            section="Quy chuẩn mã định danh nhân sự",
            proposed_content=(
                "Mã nhân sự được chuẩn hóa theo định dạng `NV-XXXXXX` (tiền tố NV kết hợp 6 chữ số định danh). "
                "Tất cả hệ thống nội bộ phải đồng bộ theo quy chuẩn này."
            ),
            rationale="Tránh trùng lặp mã khi quy mô nhân sự vượt ngưỡng 10,000 nhân viên.",
            base_hash=None,
            status="APPROVED",
            created_at=datetime.now(UTC).isoformat(),
            reviewed_at=datetime.now(UTC).isoformat(),
            reviewed_by="Ryan Truong",
            review_note="Đã đối soát với kiến trúc sư trưởng và phê duyệt áp dụng toàn hệ thống.",
        )
        self._proposal_path(p2.id).write_text(
            json.dumps(p2.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _proposal_path(self, proposal_id: str) -> Path:
        if not re.match(r"^PROP-[A-Za-z0-9_-]+$", proposal_id):
            raise ValueError(f"Invalid proposal_id: {proposal_id}")
        return self.proposals_dir / f"{proposal_id}.json"

    def create(
        self,
        *,
        spec_id: str,
        title: str,
        section: str,
        proposed_content: str,
        rationale: str,
        action: Literal["UPDATE_SECTION", "CREATE_DOCUMENT", "REPLACE_DOCUMENT"] = "UPDATE_SECTION",
        supersedes_spec_id: str | None = None,
        auto_approve: bool = False,
    ) -> KbProposal:
        """Create a new proposal. If auto_approve=True and no conflicts, automatically applies to spec."""
        spec_file = resolve_spec_path(self.knowledge_dir, spec_id)
        current_hash = file_hash(spec_file)

        # --- Deduplication Protection ---
        clean_content = re.sub(r"\s+", " ", proposed_content.strip().lower())
        clean_section = re.sub(r"\s+", " ", section.strip().lower())

        # 1. Check if an identical proposal is currently PENDING
        for existing in self.list_all(status="PENDING"):
            if (
                existing.spec_id.upper() == spec_id.strip().upper()
                and re.sub(r"\s+", " ", existing.section.strip().lower()) == clean_section
                and re.sub(r"\s+", " ", existing.proposed_content.strip().lower()) == clean_content
            ):
                raise DuplicateProposalError(
                    f"Đã có đề xuất '{existing.id}' đang chờ duyệt với cùng nội dung tại mục '{section}' của tài "
                    f"liệu {spec_id}."
                )

        # 2. Check if the proposed content is already present in the target document (No-op change)
        if spec_file.is_file():
            try:
                doc_text = spec_file.read_text(encoding="utf-8")
                clean_doc = re.sub(r"\s+", " ", doc_text.strip().lower())
                if clean_content and clean_content in clean_doc:
                    raise DuplicateProposalError(
                        f"Nội dung đề xuất này đã tồn tại trong tài liệu {spec_id}. Không cần tạo yêu cầu thay đổi "
                        "trùng lặp."
                    )
            except Exception as e:
                log.warning("[ProposalStore] Could not check doc text for duplicates: %s", e)

        # 3. Check if an identical proposal was already APPROVED
        for existing in self.list_all(status="APPROVED"):
            if (
                existing.spec_id.upper() == spec_id.strip().upper()
                and re.sub(r"\s+", " ", existing.section.strip().lower()) == clean_section
                and re.sub(r"\s+", " ", existing.proposed_content.strip().lower()) == clean_content
            ):
                raise DuplicateProposalError(
                    f"Nội dung này đã từng được phê duyệt trong đề xuất '{existing.id}' "
                    f"(Duyệt bởi: {existing.reviewed_by or 'N/A'}). Không thể gửi lại yêu cầu trùng lặp."
                )

        # --- Anti-Collision Check (Soft-Flagging for Human Gate) ---
        # a guardrail spec (memory_tier: reflective) states the forbidden patterns: checked against them, every change
        # to it was flagged by its own wording ("CẤM … float") and needed force
        reflective = spec_file.is_file() and (
            parse_frontmatter(spec_file.read_text(encoding="utf-8"))[0].get("memory_tier") == "reflective"
        )
        conflict_check = (
            ConflictCheckResult(conflict_detected=False)
            if reflective
            else detect_conflicts(spec_id=spec_id, proposed_content=proposed_content, section=section)
        )

        timestamp_str = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        rand_suffix = hashlib.sha256(f"{spec_id}:{section}:{timestamp_str}:{proposed_content}".encode()).hexdigest()[:6]
        proposal_id = f"PROP-{timestamp_str}-{rand_suffix}"

        is_auto_approved = auto_approve and not conflict_check.conflict_detected
        now_iso = datetime.now(UTC).isoformat()

        proposal = KbProposal(
            id=proposal_id,
            spec_id=spec_id,
            title=title.strip() or f"Update {spec_id}",
            action=action,
            section=section.strip(),
            proposed_content=proposed_content.strip(),
            rationale=rationale.strip(),
            base_hash=current_hash,
            status="APPROVED" if is_auto_approved else "PENDING",
            supersedes_spec_id=supersedes_spec_id.strip() if supersedes_spec_id else None,
            conflict_detected=conflict_check.conflict_detected,
            conflict_rule_id=conflict_check.rule_id,
            conflict_reason=conflict_check.reason,
            created_at=now_iso,
            reviewed_at=now_iso if is_auto_approved else None,
            reviewed_by="Auto-Approved (Agent Governance)" if is_auto_approved else None,
            review_note="Tự động áp dụng vào tài liệu và cập nhật kho tri thức" if is_auto_approved else None,
        )

        if is_auto_approved:
            apply_to_spec(proposal, spec_file)
            log.info("[ProposalStore] Proposal %s AUTO-APPROVED and applied to %s", proposal_id, spec_id)
        else:
            log.info("[ProposalStore] Created proposal %s for spec %s (status: %s)", proposal_id, spec_id, proposal.status)

        path = self._proposal_path(proposal_id)
        path.write_text(json.dumps(proposal.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        return proposal

    def get(self, proposal_id: str) -> KbProposal | None:
        """Retrieve proposal by ID."""
        path = self._proposal_path(proposal_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return KbProposal.model_validate(data)

    def list_all(self, status: str | None = None) -> list[KbProposal]:
        """List proposals, optionally filtering by status."""
        proposals: list[KbProposal] = []
        for file in sorted(self.proposals_dir.glob("PROP-*.json"), reverse=True):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                prop = KbProposal.model_validate(data)
                if status is None or prop.status == status:
                    proposals.append(prop)
            except Exception as e:
                log.warning("[ProposalStore] Failed to parse proposal %s: %s", file.name, e)
        return proposals

    async def approve(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        embedder: any,
        vectors: VectorStore,
        documents: DocumentStore,
        force: bool = False,
    ) -> KbProposal:
        """Approve proposal: applies markdown update, triggers re-ingestion, and marks APPROVED."""
        prop = self.get(proposal_id)
        if not prop:
            raise ProposalNotFoundError(f"Proposal {proposal_id} not found")
        if prop.status != "PENDING":
            raise ValueError(f"Proposal {proposal_id} is already {prop.status}")

        spec_file = resolve_spec_path(self.knowledge_dir, prop.spec_id)
        current_hash = file_hash(spec_file)

        # Optimistic Concurrency Control (OCC) check
        if not force and prop.base_hash and current_hash != prop.base_hash:
            raise ProposalConflictError(
                f"Tài liệu {prop.spec_id} đã bị chỉnh sửa kể từ khi đề xuất này được tạo "
                f"(Base hash: {prop.base_hash[:8]}, Hiện tại: {current_hash[:8] if current_hash else 'None'}). "
                "Vui lòng kiểm tra lại nội dung trước khi duyệt (hoặc dùng cờ force=True)."
            )

        # Anti-Collision Negative Constraint check (Hard-Block on approval unless forced)
        if not force and prop.conflict_detected:
            raise ProposalConflictError(
                f"Không thể phê duyệt: Đề xuất vi phạm Negative Constraint [{prop.conflict_rule_id}]: "
                f"{prop.conflict_reason}. "
                "Yêu cầu bật cờ force=True để ghi đè quy chuẩn."
            )

        apply_to_spec(prop, spec_file)

        # Ingest the modified document: automatically closes old chunks (valid_to = now) and embeds new chunks
        await ingest_documents(
            [spec_file],
            embedder=embedder,
            vectors=vectors,
            documents=documents,
            observed_at=datetime.now(UTC),
        )

        # If proposal supersedes an old spec, tombstone the old spec
        if prop.supersedes_spec_id:
            try:
                old_file = resolve_spec_path(self.knowledge_dir, prop.supersedes_spec_id)
                if old_file.is_file():
                    now_utc = datetime.now(UTC)
                    now_iso = now_utc.isoformat()
                    old_text = old_file.read_text(encoding="utf-8")
                    if old_text.startswith("---"):
                        parts = old_text.split("---", 2)
                        fm = parts[1]
                        if "status:" in fm:
                            fm = re.sub(r"status:\s*.*", "status: SUPERSEDED", fm)
                        else:
                            fm += "\nstatus: SUPERSEDED"
                        fm += f"\nvalid_to: '{now_iso}'\nsuperseded_by: '{prop.spec_id}'\n"
                        old_file.write_text(f"---{fm}---{parts[2]}", encoding="utf-8")

                    if hasattr(vectors, "tombstone_source"):
                        await vectors.tombstone_source(
                            prop.supersedes_spec_id, superseded_by=prop.spec_id, observed_at=now_utc
                        )
                    log.info(
                        "[ProposalStore] Tombstoned old spec %s (superseded by %s)",
                        prop.supersedes_spec_id,
                        prop.spec_id,
                    )
            except Exception as e:
                log.warning("[ProposalStore] Failed to tombstone spec %s: %s", prop.supersedes_spec_id, e)

        # Update proposal status
        prop.status = "APPROVED"
        prop.reviewed_at = datetime.now(UTC).isoformat()
        prop.reviewed_by = reviewer
        path = self._proposal_path(proposal_id)
        path.write_text(json.dumps(prop.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("[ProposalStore] Proposal %s APPROVED and applied to %s", proposal_id, prop.spec_id)
        return prop

    def reject(self, proposal_id: str, *, reviewer: str, note: str | None = None) -> KbProposal:
        """Reject proposal."""
        prop = self.get(proposal_id)
        if not prop:
            raise ProposalNotFoundError(f"Proposal {proposal_id} not found")
        if prop.status != "PENDING":
            raise ValueError(f"Proposal {proposal_id} is already {prop.status}")

        prop.status = "REJECTED"
        prop.reviewed_at = datetime.now(UTC).isoformat()
        prop.reviewed_by = reviewer
        prop.review_note = note
        path = self._proposal_path(proposal_id)
        path.write_text(json.dumps(prop.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("[ProposalStore] Proposal %s REJECTED by %s", proposal_id, reviewer)
        return prop
