"""The DocumentStore port, on every memory backend (PoC-A2, #297)."""


async def test_a_spec_is_stored_whole_and_read_back_by_id(document_store):
    await document_store.put(
        "SPC-2", title="Luồng thanh toán", content="---\nid: SPC-2\n---\n# 1. Tổng quan\n| a | b |\n"
    )

    doc = await document_store.get("SPC-2")

    assert doc.spec_id == "SPC-2" and doc.title == "Luồng thanh toán"
    assert doc.content == "---\nid: SPC-2\n---\n# 1. Tổng quan\n| a | b |\n"


async def test_storing_again_replaces_the_previous_text(document_store):
    await document_store.put("SPC-2", title="v1", content="old")
    await document_store.put("SPC-2", title="v2", content="new")

    assert (await document_store.get("SPC-2")).content == "new"


async def test_an_unknown_spec_is_none(document_store):
    assert await document_store.get("SPC-404") is None


async def test_ensure_is_idempotent(document_store):
    await document_store.ensure()


async def test_all_specs_are_listed_by_id(document_store):
    await document_store.put("SPC-2", title="Thanh toán", content="b")
    await document_store.put("SPC-1", title="Đăng nhập", content="a")

    assert [(d.spec_id, d.title) for d in await document_store.all()] == [
        ("SPC-1", "Đăng nhập"),
        ("SPC-2", "Thanh toán"),
    ]


async def test_a_deleted_spec_is_gone(document_store):
    await document_store.put("SPC-5", title="Từ điển dữ liệu", content="---\nid: SPC-5\n---\n")

    await document_store.delete("SPC-5")
    await document_store.delete("SPC-5")  # deleting again is not an error

    assert await document_store.get("SPC-5") is None
