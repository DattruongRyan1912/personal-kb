"""Unit and integration tests for Phase 2: Golden Exemplars, ADRs, and Tombstone Lifecycle."""

from pathlib import Path

import pytest

from personal_kb.mcp.server import create_mcp_server, setup_mcp_context
from personal_kb.services.chunking import parse_frontmatter
from personal_kb.services.memory_ports import SpecDocument
from personal_kb.services.proposals import ProposalStore
from personal_kb.tools.base import ToolContext


class DummyRetriever:
    async def search(self, query: str, as_of=None, project_id: str | None = None):
        return []


class DummyExemplarDocs:
    def __init__(self):
        root = Path(__file__).resolve().parents[2] / "knowledge"
        self._docs = {}
        for path in root.rglob("*.md"):
            if "proposals" not in path.parts:
                content = path.read_text(encoding="utf-8")
                meta, _ = parse_frontmatter(content)
                spec_id = str(meta.get("id") or path.stem)
                self._docs[spec_id] = SpecDocument(
                    spec_id=spec_id,
                    title=meta.get("title", spec_id),
                    content=content,
                )

    async def get(self, spec_id: str):
        return self._docs.get(spec_id)

    async def all(self):
        return list(self._docs.values())


@pytest.fixture
def mcp_server_with_exemplars():
    ctx = ToolContext(retriever=DummyRetriever(), documents=DummyExemplarDocs())
    setup_mcp_context(ctx)
    return create_mcp_server()


async def test_recall_exemplar_payroll(mcp_server_with_exemplars):
    """Test retrieving payroll calculation exemplar (HR-EX-001)."""
    res = await mcp_server_with_exemplars.call_tool("recall_exemplar", {"project": "Demo-Core", "pattern": "payroll"})
    assert not res.is_error
    text = res.content[0].text
    assert "HR-EX-001" in text
    assert "Decimal" in text
    assert "compute_monthly_payroll" in text
    assert "ROUND_HALF_UP" in text
    assert "Zero-Tolerance" in text


async def test_recall_exemplar_timesheet(mcp_server_with_exemplars):
    """Test retrieving timesheet adjustment exemplar (HR-EX-002)."""
    res = await mcp_server_with_exemplars.call_tool("recall_exemplar", {"project": "Demo-Core", "pattern": "timesheet"})
    assert not res.is_error
    text = res.content[0].text
    assert "HR-EX-002" in text
    assert "timesheet_adjustments" in text
    assert "PeriodStatus.LOCKED" in text


async def test_recall_exemplar_mcp_tool(mcp_server_with_exemplars):
    """Test retrieving MCP tool pattern exemplar (PKB-EX-001)."""
    res = await mcp_server_with_exemplars.call_tool("recall_exemplar", {"project": "Personal-KB", "pattern": "mcp"})
    assert not res.is_error
    text = res.content[0].text
    assert "PKB-EX-001" in text
    assert "MCPServer" in text
    assert "register_production_tool" in text


async def test_recall_exemplar_unknown_project(mcp_server_with_exemplars):
    """Test error handling when project has no exemplars."""
    res = await mcp_server_with_exemplars.call_tool("recall_exemplar", {"project": "NON_EXISTENT_PROJ"})
    assert not res.is_error
    assert "Không tìm thấy Golden Exemplar" in res.content[0].text


async def test_tombstone_lifecycle_in_proposals(tmp_path):
    """Test proposal with supersedes_spec_id updates old spec with tombstone metadata."""
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir(parents=True)
    proposals_dir = knowledge_dir / "proposals"
    proposals_dir.mkdir(parents=True)

    # 1. Create an existing obsolete spec
    old_spec_file = knowledge_dir / "HR-OLD-01.md"
    old_spec_file.write_text(
        "---\nid: HR-OLD-01\ntitle: Quy định cũ thời kỳ 2024\nstatus: active\n---\n# Nội dung cũ\n",
        encoding="utf-8",
    )

    # 2. Mock vector store with tombstone_source
    class MockVectorStore:
        def __init__(self):
            self.tombstoned = []

        async def tombstone_source(self, source_id, *, superseded_by, observed_at):
            self.tombstoned.append((source_id, superseded_by))
            return 1

        async def known_chunk_keys(self, s):
            return set()

        async def apply_revision(self, *a, **k):
            from personal_kb.services.memory_ports import VectorRevisionResult

            return VectorRevisionResult(added=1, closed=0)

    class MockEmbedder:
        async def embed(self, t):
            return [[0.1] * 10]

    class MockDocStore:
        async def put(self, *a, **k):
            pass

    store = ProposalStore(knowledge_dir=knowledge_dir)
    prop = store.create(
        spec_id="HR-NEW-01",
        title="Quy định mới thay thế HR-OLD-01",
        section="Toàn văn",
        proposed_content="# Nội dung mới hiện đại",
        rationale="Cập nhật quy định mới 2026",
        action="CREATE_DOCUMENT",
        supersedes_spec_id="HR-OLD-01",
    )

    assert prop.supersedes_spec_id == "HR-OLD-01"

    # 3. Approve proposal
    mock_vectors = MockVectorStore()
    approved = await store.approve(
        prop.id,
        reviewer="Ryan Architect",
        embedder=MockEmbedder(),
        vectors=mock_vectors,
        documents=MockDocStore(),
    )

    assert approved.status == "APPROVED"
    assert ("HR-OLD-01", "HR-NEW-01") in mock_vectors.tombstoned

    # 4. Check that old file was tombstoned (status: SUPERSEDED, valid_to and superseded_by recorded)
    old_content = old_spec_file.read_text(encoding="utf-8")
    assert "status: SUPERSEDED" in old_content
    assert "superseded_by: 'HR-NEW-01'" in old_content
    assert "valid_to:" in old_content
