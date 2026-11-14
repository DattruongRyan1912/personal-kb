from pathlib import Path
from unittest.mock import AsyncMock

from personal_kb.services.proposals import ProposalStore


async def test_an_approved_full_document_keeps_its_final_newline(tmp_path):
    # the stored proposal is stripped; written back as is, the spec lost its last newline (CYBEROS-01, 2026-10-25)
    spec = tmp_path / "SPEC-A.md"
    spec.write_text("---\nid: SPEC-A\ntitle: Old\n---\n\nBody.\n", encoding="utf-8")
    store = ProposalStore(knowledge_dir=tmp_path)
    prop = store.create(
        spec_id="SPEC-A",
        title="Rename",
        section="",
        proposed_content="---\nid: SPEC-A\ntitle: New\n---\n\nBody.\n",
        rationale="title matches the content",
        action="REPLACE_DOCUMENT",
    )
    vectors = AsyncMock()
    vectors.known_chunk_keys.return_value = set()

    embedder = AsyncMock()
    embedder.embed.side_effect = lambda texts: [[0.0] * 4 for _ in texts]

    await store.approve(prop.id, reviewer="r", embedder=embedder, vectors=vectors, documents=AsyncMock())

    assert spec.read_text(encoding="utf-8") == "---\nid: SPEC-A\ntitle: New\n---\n\nBody.\n"


def test_the_cli_and_the_store_apply_a_proposal_with_the_same_code(tmp_path):
    # scripts/manage_proposals.py had its own copy of the apply step, without the final-newline fix
    from personal_kb.services.proposals import apply_to_spec

    spec = tmp_path / "SPEC-A.md"
    spec.write_text("old\n", encoding="utf-8")
    store = ProposalStore(knowledge_dir=tmp_path)
    prop = store.create(
        spec_id="SPEC-A", title="t", section="", proposed_content="new\n", rationale="r", action="REPLACE_DOCUMENT"
    )

    apply_to_spec(prop, spec)

    assert spec.read_text(encoding="utf-8") == "new\n"
    script = (Path(__file__).resolve().parents[2] / "scripts" / "manage_proposals.py").read_text()
    assert "apply_to_spec(" in script and "spec_file.write_text(prop.proposed_content" not in script


async def test_approving_through_the_api_writes_the_spec(tmp_path):
    # the route looked up retriever.embedder, which HybridRetriever did not expose: every web approval fell into the
    # test-only branch, said APPROVED and left the spec unchanged (found 2026-10-25)
    from types import SimpleNamespace

    from httpx import ASGITransport, AsyncClient

    from personal_kb.api.proposals import get_proposal_store
    from personal_kb.main import create_app
    from personal_kb.services.retrieval import HybridRetriever
    from tests.conftest import auth_headers, make_settings

    spec = tmp_path / "SPEC-A.md"
    spec.write_text("---\nid: SPEC-A\ntitle: Old\n---\n\nBody.\n", encoding="utf-8")
    store = ProposalStore(knowledge_dir=tmp_path)
    prop = store.create(
        spec_id="SPEC-A",
        title="t",
        section="",
        rationale="r",
        action="REPLACE_DOCUMENT",
        proposed_content="---\nid: SPEC-A\ntitle: New\n---\n\nBody.\n",
    )
    embedder = AsyncMock()
    embedder.embed.side_effect = lambda texts: [[0.0] * 4 for _ in texts]
    vectors = AsyncMock()
    vectors.known_chunk_keys.return_value = set()
    app = create_app(make_settings())
    app.dependency_overrides[get_proposal_store] = lambda: store
    app.state.stores = SimpleNamespace(vectors=vectors, documents=AsyncMock())
    app.state.retriever = HybridRetriever(
        embedder=embedder, vectors=vectors, term_extractor=AsyncMock(), graph=AsyncMock(), reranker=AsyncMock()
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(f"/api/v1/proposals/{prop.id}/approve", headers=auth_headers(), json={"reviewer": "r"})

    assert res.status_code == 200 and res.json()["status"] == "APPROVED"
    assert "title: New" in spec.read_text(encoding="utf-8")
