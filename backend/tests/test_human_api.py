import pytest
from httpx import ASGITransport, AsyncClient

from personal_kb.api.specs import get_documents
from personal_kb.main import create_app
from tests.conftest import auth_headers, make_settings
from tests.fakes import InMemoryDocumentStore

SPC_2 = "---\nid: SPC-2\ntitle: Luồng thanh toán đơn hàng\nowner: Ryan Truong\nstatus: APPROVED\n---\n# 1. Tổng quan\n"


@pytest.fixture
async def documents():
    store = InMemoryDocumentStore()
    await store.put("SPC-2", title="Luồng thanh toán đơn hàng", content=SPC_2)
    return store


async def test_human_protocol_specs_endpoint(documents):
    app = create_app(make_settings())
    app.dependency_overrides[get_documents] = lambda: documents
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Test new Human Protocol namespace
        resp_human = await client.get("/api/v1/human/specs/SPC-2", headers=auth_headers())
        assert resp_human.status_code == 200
        assert resp_human.json() == {
            "spec_id": "SPC-2",
            "title": "Luồng thanh toán đơn hàng",
            "owner": "Ryan Truong",
            "status": "APPROVED",
        }

        # 2. Test backwards compatibility (direct /api/v1/specs/SPC-2 for existing frontend)
        resp_compat = await client.get("/api/v1/specs/SPC-2", headers=auth_headers())
        assert resp_compat.status_code == 200
        assert resp_compat.json() == resp_human.json()
