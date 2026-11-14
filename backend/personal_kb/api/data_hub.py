"""Data Management & Storage Hub APIs for Personal-KB (/api/v1/data).

Storage it reports on:
- PostgreSQL 17 + pgvector (chunks, documents, graph, worklog)
- Local Disk (knowledge/*.md)
- Redis 7 (Session Cache)
- Proposals Staging (JSON Governance)
"""

import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

from personal_kb.core.auth import current_user
from personal_kb.services.chunking import parse_frontmatter
from personal_kb.services.ingestion import ingest_documents
from personal_kb.services.knowledge_files import (
    InvalidSpecPath,
    find_spec_file,
    knowledge_dir,
    new_spec_path,
    spec_files,
    spec_id_of,
    title_of,
)
from personal_kb.services.projects import project_of

log = logging.getLogger(__name__)

# signed-in only: an upload is a CORS "simple request", so an open route would let any web page write to knowledge/
router = APIRouter(prefix="/api/v1/data", tags=["data-hub"], dependencies=[Depends(current_user)])


# --- Schemas ---


class CatalogItem(BaseModel):
    spec_id: str
    title: str
    project_id: str = "Personal-KB"
    file_name: str
    file_size_bytes: int
    chunk_count: int
    in_vector_db: bool
    in_documents: bool
    last_modified: str


class CatalogResponse(BaseModel):
    total_specs: int
    total_chunks: int
    storage_backend: str
    projects: list[str] = []
    project_counts: dict[str, int] = {}
    items: list[CatalogItem]


class StorageTierStats(BaseModel):
    name: str
    engine: str
    status: str
    metrics: dict[str, Any]


class TopologyResponse(BaseModel):
    storage_backend: str
    embedding_model: str
    embedding_dimensions: int
    tiers: list[StorageTierStats]
    timestamp: str


class ConsistencyAuditResult(BaseModel):
    total_disk_files: int
    total_db_specs: int
    missing_in_db: list[str]  # files on disk without vectors in DB
    orphan_in_db: list[str]  # specs in DB without file on disk
    consistency_percentage: float
    audit_passed: bool
    timestamp: str


class ChunkItem(BaseModel):
    chunk_id: int | str
    chunk_key: str
    chunk_index: int
    headings: list[str]
    content: str
    token_estimate: int
    status: str
    valid_from: str | None = None


class ChunksListResponse(BaseModel):
    spec_id: str
    total_chunks: int
    chunks: list[ChunkItem]


class RetrievalTestRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query to test")
    limit: int = Field(5, ge=1, le=20)
    project_id: str | None = Field(None, description="Lọc theo dự án nếu có")


class HitItem(BaseModel):
    spec_ids: list[str]
    headings: list[str]
    source: str
    score: float
    text_preview: str
    project_id: str = "Personal-KB"


class RetrievalTestResponse(BaseModel):
    query: str
    took_ms: float
    total_hits: int
    results: list[HitItem]


# --- Helpers ---


def get_knowledge_dir() -> Path:
    return knowledge_dir()


def _checked(path_of, *args) -> Path:
    try:
        return path_of(*args)
    except InvalidSpecPath as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _run_async_ingestion(request: Request, spec_file: Path, spec_id: str) -> None:
    try:
        log.info("[DataHub] Bắt đầu background ingestion cho: %s", spec_id)
        embedder = request.app.state.retriever.embedder
        stores = request.app.state.stores
        await ingest_documents(
            [spec_file],
            embedder=embedder,
            vectors=stores.vectors,
            documents=stores.documents,
            observed_at=datetime.now(UTC),
        )
        log.info("[DataHub] Hoàn tất background ingestion cho: %s", spec_id)
    except Exception as e:
        log.exception("[DataHub] Lỗi trong background ingestion cho %s: %s", spec_id, e)


# --- Endpoints ---


@router.get("/catalog", response_model=CatalogResponse)
async def list_catalog(request: Request, project: str | None = Query(None)) -> CatalogResponse:
    """Liệt kê toàn bộ tài liệu nguồn trong kho và trạng thái đồng bộ sang Vector DB."""
    knowledge_dir = get_knowledge_dir()
    stores = request.app.state.stores
    settings = request.app.state.settings

    chunk_counts: dict[str, int] = {}

    # 1. Query chunks from PostgreSQL if active
    if stores.pg is not None:
        try:
            schema = settings.postgres_schema
            query = (
                f"SELECT spec_id, count(*)::int as count FROM {schema}.chunks WHERE valid_to IS NULL GROUP BY spec_id;"
            )
            rows = await stores.pg.fetch(query)
            for r in rows:
                chunk_counts[r["spec_id"]] = r["count"]
        except Exception as e:
            log.warning("[DataHub] Không thể lấy chunk count từ Postgres: %s", e)

    # Query documents in DocumentStore
    doc_ids: set[str] = set()
    try:
        all_docs = await stores.documents.all()
        doc_ids = {d.spec_id for d in all_docs}
    except Exception as e:
        log.warning("[DataHub] Không thể lấy all docs từ DocumentStore: %s", e)

    items: list[CatalogItem] = []
    total_chunks = 0
    all_projects: set[str] = set()
    project_counts: dict[str, int] = {}

    if knowledge_dir.exists():
        for p in sorted(knowledge_dir.rglob("*.md")):
            if p.is_file() and not p.name.startswith(".") and "proposals" not in p.parts:
                spec_id = p.stem
                file_size = p.stat().st_size
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat()
                try:
                    content = p.read_text(encoding="utf-8")
                    spec_id = spec_id_of(p, content)  # KB-01 lives in KB-01-huong-dan.md
                    title = title_of(content, default=spec_id)
                    spec_project = project_of(spec_id, parse_frontmatter(content)[0], p)
                except Exception:
                    title = spec_id
                    spec_project = "Personal-KB"

                all_projects.add(spec_project)
                project_counts[spec_project] = project_counts.get(spec_project, 0) + 1

                c_count = chunk_counts.get(spec_id, 0)
                total_chunks += c_count

                # Filter by project query param if specified (and not 'ALL')
                if project and project != "ALL" and spec_project != project:
                    continue

                items.append(
                    CatalogItem(
                        spec_id=spec_id,
                        title=title,
                        project_id=spec_project,
                        file_name=p.name,
                        file_size_bytes=file_size,
                        chunk_count=c_count,
                        in_vector_db=c_count > 0,
                        in_documents=spec_id in doc_ids,
                        last_modified=mtime,
                    )
                )

    projects_list = sorted(list(all_projects))
    if not projects_list:
        projects_list = ["Personal-KB"]

    return CatalogResponse(
        total_specs=len(items),
        total_chunks=total_chunks,
        storage_backend="postgres",
        projects=projects_list,
        project_counts=project_counts,
        items=items,
    )


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project_id: str = Form("Personal-KB"),
) -> dict[str, Any]:
    """Tải lên tài liệu mới (.md, .txt), lưu vào kho knowledge và trigger nhúng vector tự động."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Không có file được chọn")

    filename = file.filename
    if not (filename.endswith(".md") or filename.endswith(".txt")):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file định dạng Markdown (.md) hoặc Text (.txt)")

    raw_stem = Path(filename).stem
    cleaned_spec_id = re.sub(r"[^A-Za-z0-9_.-]", "_", raw_stem)
    if not cleaned_spec_id:
        cleaned_spec_id = f"doc_{int(time.time())}"

    safe_project = re.sub(r"[^A-Za-z0-9_.-]", "_", project_id.strip()) if project_id else "Personal-KB"
    knowledge_dir = get_knowledge_dir()
    target_path = _checked(new_spec_path, knowledge_dir, cleaned_spec_id, safe_project)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    content_bytes = await file.read()
    content_str = content_bytes.decode("utf-8", errors="replace")

    # If file does not have project frontmatter, ensure it is added
    if not re.search(r"^---\s*\n.*?(?:project|project_id):\s*.*?\n---", content_str, re.DOTALL):
        if content_str.startswith("---\n"):
            parts = content_str.split("---\n", 2)
            if len(parts) >= 3:
                content_str = f"---\nproject: {safe_project}\n{parts[1]}---\n{parts[2]}"
            else:
                content_str = f"---\nproject: {safe_project}\n---\n\n{content_str}"
        else:
            content_str = f"---\nproject: {safe_project}\n---\n\n{content_str}"

    target_path.write_text(content_str, encoding="utf-8")
    cleaned_spec_id = spec_id_of(target_path, content_str)  # a frontmatter id wins over the file name, as in ingestion

    # Queue background ingestion
    background_tasks.add_task(_run_async_ingestion, request, target_path, cleaned_spec_id)

    return {
        "status": "processing",
        "spec_id": cleaned_spec_id,
        "project_id": safe_project,
        "file_name": target_path.name,
        "message": (
            f"Tài liệu {cleaned_spec_id} thuộc dự án [{safe_project}] đã được lưu "
            "và đang xử lý cắt đoạn/nhúng vector trong nền."
        ),
    }


@router.post("/reindex/{spec_id}", status_code=status.HTTP_202_ACCEPTED)
async def reindex_spec(
    spec_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Kích hoạt chạy lại quá trình phân mảnh và sinh embedding cho tài liệu."""
    target_path = find_spec_file(get_knowledge_dir(), spec_id)

    if target_path is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file tài liệu {spec_id}.md")

    background_tasks.add_task(_run_async_ingestion, request, target_path, spec_id)

    return {
        "status": "processing",
        "spec_id": spec_id,
        "message": f"Đã kích hoạt re-index cho {spec_id}. Đang chạy trong nền.",
    }


@router.delete("/documents/{spec_id}")
async def delete_document(spec_id: str, request: Request) -> dict[str, Any]:
    """Xóa tài liệu khỏi đĩa cứng và dọn sạch dữ liệu liên quan trong Vector Store."""
    target_path = find_spec_file(get_knowledge_dir(), spec_id)

    stores = request.app.state.stores

    try:
        await stores.vectors.delete_source(spec_id)
    except Exception as e:
        log.warning("[DataHub] Lỗi khi delete_source trong vectors: %s", e)

    try:
        await stores.documents.delete(spec_id)
    except Exception as e:
        log.warning("[DataHub] Lỗi khi delete trong document store: %s", e)

    file_deleted = False
    if target_path is not None:
        target_path.unlink()
        file_deleted = True

    return {
        "status": "deleted",
        "spec_id": spec_id,
        "file_deleted": file_deleted,
        "message": f"Đã xóa tài liệu {spec_id} và dọn sạch các vector liên quan.",
    }


@router.get("/topology", response_model=TopologyResponse)
async def get_storage_topology(request: Request) -> TopologyResponse:
    """Trả về chi tiết hiện trạng phân bổ lưu trữ trên toàn bộ các tầng dữ liệu (Dynamic Adapter)."""
    settings = request.app.state.settings
    stores = request.app.state.stores
    knowledge_dir = get_knowledge_dir()

    tiers: list[StorageTierStats] = []

    # 1. Local Disk Store
    local_files = (
        [
            p
            for p in knowledge_dir.rglob("*.md")
            if p.is_file() and not p.name.startswith(".") and "proposals" not in p.parts
        ]
        if knowledge_dir.exists()
        else []
    )
    local_bytes = sum(p.stat().st_size for p in local_files)
    tiers.append(
        StorageTierStats(
            name="Kho Tệp Tin Cục Bộ (Local Files)",
            engine="POSIX File System",
            status="Active",
            metrics={
                "path": str(knowledge_dir),
                "total_documents": len(local_files),
                "total_bytes": local_bytes,
                "human_size": f"{local_bytes / 1024:.1f} KB",
            },
        )
    )

    # 3. PostgreSQL 17 + pgvector (Khi active hoặc khi được cấu hình)
    if stores.pg is not None:
        schema = settings.postgres_schema
        pg_metrics: dict[str, Any] = {
            "schema": schema,
            "dimensions": settings.embedding_dimensions,
            "hnsw_index": "cosine (chunks_embedding)",
        }
        try:
            chunks_cnt = await stores.pg.fetchval(f"SELECT count(*)::int FROM {schema}.chunks WHERE valid_to IS NULL;")
            closed_cnt = await stores.pg.fetchval(
                f"SELECT count(*)::int FROM {schema}.chunks WHERE valid_to IS NOT NULL;"
            )
            docs_cnt = await stores.pg.fetchval(f"SELECT count(*)::int FROM {schema}.documents;")
            chunks_size = await stores.pg.fetchval(f"SELECT pg_total_relation_size('{schema}.chunks');") or 0
            docs_size = await stores.pg.fetchval(f"SELECT pg_total_relation_size('{schema}.documents');") or 0

            pg_metrics["active_chunks"] = chunks_cnt
            pg_metrics["historical_chunks"] = closed_cnt
            pg_metrics["stored_documents"] = docs_cnt
            pg_metrics["table_chunks_size_bytes"] = chunks_size
            pg_metrics["table_chunks_human"] = f"{chunks_size / (1024 * 1024):.2f} MB"
            pg_metrics["table_docs_size_bytes"] = docs_size
            status_pg = "Online"
        except Exception as e:
            pg_metrics["error"] = str(e)
            status_pg = "Degraded"

        tiers.append(
            StorageTierStats(
                name="Cơ Sở Dữ Liệu Quan Hệ & Vector (PostgreSQL 17)",
                engine=f"PostgreSQL 17 + pgvector ({settings.embedding_dimensions}d)",
                status=status_pg,
                metrics=pg_metrics,
            )
        )

    # 4. Redis Cache
    redis_metrics: dict[str, Any] = {
        "url": settings.redis_url.split("@")[-1] if "@" in settings.redis_url else settings.redis_url,
    }
    try:
        redis_client = getattr(request.app.state.memory, "_redis", None)
        if redis_client:
            info = await redis_client.info()
            dbsize = await redis_client.dbsize()
            redis_metrics["total_keys"] = dbsize
            redis_metrics["used_memory_human"] = info.get("used_memory_human", "N/A")
            redis_metrics["connected_clients"] = info.get("connected_clients", 1)
            status_redis = "Online"
        else:
            status_redis = "Not available"
    except Exception as e:
        redis_metrics["error"] = str(e)
        status_redis = "Unavailable"

    tiers.append(
        StorageTierStats(
            name="Bộ Nhớ Đệm Phiên & Truy Hồi (Redis)",
            engine="Redis 7 (In-Memory Key-Value)",
            status=status_redis,
            metrics=redis_metrics,
        )
    )

    # 5. Governance & Proposals Store
    proposals_dir = knowledge_dir / "proposals"
    prop_pending, prop_approved, prop_rejected = 0, 0, 0
    if proposals_dir.exists():
        for f in proposals_dir.glob("*.json"):
            name = f.name.lower()
            if "approved" in name:
                prop_approved += 1
            elif "rejected" in name:
                prop_rejected += 1
            else:
                prop_pending += 1

    tiers.append(
        StorageTierStats(
            name="Phân Hệ Duyệt Tri Thức (Proposals)",
            engine="JSON Staging / Proposals Store",
            status="Active",
            metrics={
                "pending": prop_pending,
                "approved": prop_approved,
                "rejected": prop_rejected,
                "total": prop_pending + prop_approved + prop_rejected,
            },
        )
    )

    return TopologyResponse(
        storage_backend="postgres",
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        tiers=tiers,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.post("/audit", response_model=ConsistencyAuditResult)
async def run_consistency_audit(request: Request) -> ConsistencyAuditResult:
    """Đối soát tính nhất quán giữa các tệp nguồn trên đĩa và các vector trong cơ sở dữ liệu."""
    knowledge_dir = get_knowledge_dir()
    settings = request.app.state.settings
    stores = request.app.state.stores

    disk_files = {spec_id_of(p) for p in spec_files(knowledge_dir)} if knowledge_dir.exists() else set()
    db_specs: set[str] = set()

    # 1. Check in Postgres
    if stores.pg is not None:
        try:
            schema = settings.postgres_schema
            rows = await stores.pg.fetch(f"SELECT DISTINCT spec_id FROM {schema}.chunks WHERE valid_to IS NULL;")
            db_specs = {r["spec_id"] for r in rows}
        except Exception as e:
            log.warning("[DataHub] Lỗi khi query db_specs trong audit (pg): %s", e)

    missing_in_db = sorted(list(disk_files - db_specs))
    orphan_in_db = sorted(list(db_specs - disk_files))

    all_known = disk_files | db_specs
    consistent_count = len(all_known) - len(missing_in_db) - len(orphan_in_db)
    consistency_pct = (consistent_count / len(all_known) * 100) if all_known else 100.0

    return ConsistencyAuditResult(
        total_disk_files=len(disk_files),
        total_db_specs=len(db_specs),
        missing_in_db=missing_in_db,
        orphan_in_db=orphan_in_db,
        consistency_percentage=round(consistency_pct, 1),
        audit_passed=(len(missing_in_db) == 0 and len(orphan_in_db) == 0),
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/documents/{spec_id}/chunks", response_model=ChunksListResponse)
async def get_document_chunks(spec_id: str, request: Request) -> ChunksListResponse:
    """Trích xuất danh sách tất cả các chunks đã phân đoạn của một spec cụ thể (từ PostgreSQL)."""
    settings = request.app.state.settings
    stores = request.app.state.stores

    chunks: list[ChunkItem] = []

    # 1. From PostgreSQL
    if stores.pg is not None:
        schema = settings.postgres_schema
        query = f"""
            SELECT id, chunk_key, chunk_index, headings, content, status, valid_from
            FROM {schema}.chunks
            WHERE spec_id = $1 AND valid_to IS NULL
            ORDER BY chunk_index ASC;
        """
        rows = await stores.pg.fetch(query, spec_id)
        for r in rows:
            content = r["content"]
            chunks.append(
                ChunkItem(
                    chunk_id=r["id"],
                    chunk_key=r["chunk_key"],
                    chunk_index=r["chunk_index"],
                    headings=r["headings"] or [],
                    content=content,
                    token_estimate=len(content.split()),
                    status=r["status"],
                    valid_from=r["valid_from"].isoformat() if r["valid_from"] else None,
                )
            )

    return ChunksListResponse(
        spec_id=spec_id,
        total_chunks=len(chunks),
        chunks=chunks,
    )


@router.post("/sandbox/retrieve", response_model=RetrievalTestResponse)
async def test_retrieval(body: RetrievalTestRequest, request: Request) -> RetrievalTestResponse:
    """Sandbox kiểm thử truy hồi trực tiếp từ Hybrid Retriever để đánh giá độ chính xác và tốc độ."""
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is None:
        raise HTTPException(status_code=503, detail="Retriever chưa sẵn sàng")

    start_time = time.perf_counter()
    try:
        hits = await retriever.search(body.query, project_id=body.project_id)
    except Exception as e:
        log.exception("[DataHub] Lỗi trong sandbox retrieve: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi khi thực hiện truy hồi: {e}") from e

    took_ms = (time.perf_counter() - start_time) * 1000

    results: list[HitItem] = []
    for h in hits[: body.limit]:
        results.append(
            HitItem(
                spec_ids=h.spec_ids,
                headings=h.headings,
                source=h.source,
                score=round(h.score, 4),
                text_preview=h.text[:250] + ("..." if len(h.text) > 250 else ""),
                project_id=getattr(h, "project_id", "Personal-KB") or "Personal-KB",
            )
        )

    return RetrievalTestResponse(
        query=body.query,
        took_ms=round(took_ms, 2),
        total_hits=len(results),
        results=results,
    )
