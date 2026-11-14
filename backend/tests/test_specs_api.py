import pytest
from httpx import ASGITransport, AsyncClient

from personal_kb.api.specs import get_documents
from personal_kb.main import create_app
from tests.conftest import auth_headers, make_settings
from tests.fakes import InMemoryDocumentStore

SPC_2 = (
    "---\nid: SPC-2\ntitle: Luồng thanh toán đơn hàng\nowner: Trần Quốc Bảo\nstatus: APPROVED\n---\n# 1. Tổng quan\n"
)


@pytest.fixture
async def documents():
    store = InMemoryDocumentStore()
    await store.put("SPC-2", title="Luồng thanh toán đơn hàng", content=SPC_2)
    await store.put("SPC-9", title="", content="# Không có frontmatter\n")
    return store


async def get(documents, path, headers=None):
    app = create_app(make_settings())
    app.dependency_overrides[get_documents] = lambda: documents
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, headers=auth_headers() if headers is None else headers)


async def test_a_spec_card_has_the_title_owner_and_status_of_the_spec(documents):
    response = await get(documents, "/api/v1/specs/SPC-2")

    assert response.status_code == 200
    assert response.json() == {
        "spec_id": "SPC-2",
        "title": "Luồng thanh toán đơn hàng",
        "owner": "Trần Quốc Bảo",
        "status": "APPROVED",
    }


async def test_a_spec_without_frontmatter_still_has_a_card(documents):
    assert (await get(documents, "/api/v1/specs/SPC-9")).json() == {
        "spec_id": "SPC-9",
        "title": "SPC-9",
        "owner": None,
        "status": "APPROVED",
    }


async def test_an_unknown_spec_is_404(documents):
    response = await get(documents, "/api/v1/specs/SPC-404")

    assert response.status_code == 404 and response.json()["error"] == "SPEC_NOT_FOUND"


async def test_a_card_needs_a_signed_in_user_and_a_valid_id(documents):
    assert (await get(documents, "/api/v1/specs/SPC-2", headers={})).status_code == 401
    assert (await get(documents, "/api/v1/specs/a%20b")).status_code == 422


async def test_get_spec_content_returns_full_markdown_and_hash(documents):
    response = await get(documents, "/api/v1/specs/SPC-2/content")
    assert response.status_code == 200
    data = response.json()
    assert data["spec_id"] == "SPC-2"
    assert data["title"] == "Luồng thanh toán đơn hàng"
    assert data["status"] == "APPROVED"
    assert "# 1. Tổng quan" in data["content"]
    assert len(data["content_hash"]) == 64  # valid sha256


async def test_get_spec_content_404_for_unknown(documents):
    response = await get(documents, "/api/v1/specs/SPC-NOT-FOUND/content")
    assert response.status_code == 404
