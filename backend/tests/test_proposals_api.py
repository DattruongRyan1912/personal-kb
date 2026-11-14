import pytest
from httpx import ASGITransport, AsyncClient

from personal_kb.api.proposals import get_proposal_store
from personal_kb.main import create_app
from personal_kb.services.proposals import ProposalStore
from tests.conftest import auth_headers, make_settings


@pytest.fixture
def proposal_store(tmp_path):
    store = ProposalStore(knowledge_dir=tmp_path)
    return store


@pytest.fixture
def app(proposal_store):
    app = create_app(make_settings())
    app.dependency_overrides[get_proposal_store] = lambda: proposal_store
    return app


async def test_list_proposals_includes_seeded_samples(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/proposals", headers=auth_headers())
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 2
        ids = [p["id"] for p in data]
        assert "PROP-SEED-001" in ids
        assert "PROP-SEED-002" in ids


async def test_create_get_approve_and_reject_proposals(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create a proposal
        create_res = await client.post(
            "/api/v1/proposals",
            headers=auth_headers(),
            json={
                "spec_id": "HR-M04",
                "title": "Cập nhật chính sách thai sản mới",
                "section": "Chế độ thai sản",
                "proposed_content": "Thời gian nghỉ thai sản hưởng nguyên lương là 6 tháng.",
                "rationale": "Căn cứ Luật Lao động sửa đổi.",
            },
        )
        assert create_res.status_code == 201
        prop = create_res.json()
        prop_id = prop["id"]
        assert prop["status"] == "PENDING"
        assert prop["spec_id"] == "HR-M04"

        # 2. Get detail
        get_res = await client.get(f"/api/v1/proposals/{prop_id}", headers=auth_headers())
        assert get_res.status_code == 200
        assert get_res.json()["title"] == "Cập nhật chính sách thai sản mới"

        # 3. Approve
        approve_res = await client.post(
            f"/api/v1/proposals/{prop_id}/approve",
            headers=auth_headers(),
            json={"reviewer": "Ryan Truong", "force": True},
        )
        assert approve_res.status_code == 200
        approved = approve_res.json()
        assert approved["status"] == "APPROVED"
        assert approved["reviewed_by"] == "Ryan Truong"

        # 4. Reject another proposal (use PROP-SEED-001)
        reject_res = await client.post(
            "/api/v1/proposals/PROP-SEED-001/reject",
            headers=auth_headers(),
            json={"reviewer": "Ryan Truong", "note": "Chưa phù hợp với ngân sách công ty."},
        )
        assert reject_res.status_code == 200
        rejected = reject_res.json()
        assert rejected["status"] == "REJECTED"
        assert rejected["review_note"] == "Chưa phù hợp với ngân sách công ty."


async def test_proposal_store_auto_approve(proposal_store, tmp_path):
    # Test auto_approve=True applies changes immediately without pending status
    spec_file = tmp_path / "HR-M04.md"
    spec_file.write_text("---\nid: HR-M04\ntitle: Chế độ làm việc\n---\n\n## Mục 1\nNội dung cũ.\n", encoding="utf-8")

    prop = proposal_store.create(
        spec_id="HR-M04",
        title="Bổ sung phụ cấp ca đêm",
        section="Mục 1",
        proposed_content="Nội dung mới cập nhật tự động.",
        rationale="Cập nhật tự động không chờ duyệt.",
        auto_approve=True,
    )
    assert prop.status == "APPROVED"
    assert prop.reviewed_by == "Auto-Approved (Agent Governance)"
    assert "Nội dung mới cập nhật tự động." in spec_file.read_text(encoding="utf-8")


async def test_proposals_require_authentication(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/proposals")
        assert res.status_code == 401


async def test_duplicate_proposal_rejected_with_409(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "spec_id": "HR-M04",
            "title": "Bổ sung chính sách phụ cấp ca đêm",
            "section": "Chế độ ca đêm",
            "proposed_content": "Trợ cấp làm việc ban đêm bằng 30% tiền lương giờ thực trả.",
            "rationale": "Căn cứ thỏa ước lao động tập thể.",
        }

        # First creation succeeds (201 Created)
        res1 = await client.post("/api/v1/proposals", headers=auth_headers(), json=payload)
        assert res1.status_code == 201

        # Second creation with identical content is rejected (409 Conflict)
        res2 = await client.post("/api/v1/proposals", headers=auth_headers(), json=payload)
        assert res2.status_code == 409
        assert "đang chờ duyệt với cùng nội dung" in res2.json()["detail"]
