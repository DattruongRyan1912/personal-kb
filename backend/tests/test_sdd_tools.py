from personal_kb.core.exceptions import DependencyUnavailableError
from personal_kb.services.memory_ports import SpecDocument
from personal_kb.services.retrieval import SearchResult
from personal_kb.tools.base import ToolContext
from personal_kb.tools.sdd_knowledge import GetFullSpecContent, SearchSddKnowledge, VerifyCitation, sources_in


class FakeRetriever:
    def __init__(self, results=(), error=None):
        self.results, self.error, self.queries = list(results), error, []

    async def search(self, query):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.results


class FakeDocuments:
    def __init__(self, docs=None, error=None):
        self.docs, self.error = docs or {}, error

    async def get(self, spec_id):
        if self.error:
            raise self.error
        return self.docs.get(spec_id)


async def test_search_lists_results_with_their_spec_ids_for_citations():
    results = [
        SearchResult(
            text="API POST /api/v1/notifications/email:\n- ghi vào bảng email_outbox (MODIFIES)",
            score=0.79,
            source="graph",
            spec_ids=["SPC-3"],
        ),
        SearchResult(
            text="API nội bộ của dịch vụ Notification",
            score=0.75,
            source="vector",
            spec_ids=["SPC-3"],
            headings=["# 2. API", "## 2.2 POST /api/v1/notifications/email"],
        ),
    ]
    retriever = FakeRetriever(results)

    answer = await SearchSddKnowledge().execute(
        {"query": "API gửi mail"}, ToolContext(retriever=retriever, documents=None)
    )

    assert retriever.queries == ["API gửi mail"]
    assert "[1] (SPC-3, graph, 0.79)" in answer and "email_outbox" in answer
    assert "[2] (SPC-3, vector, 0.75) # 2. API > ## 2.2 POST /api/v1/notifications/email" in answer


async def test_search_says_so_when_nothing_matches():
    answer = await SearchSddKnowledge().execute({"query": "tên lửa"}, ToolContext(FakeRetriever([]), None))

    assert "Không tìm thấy" in answer


async def test_search_with_the_store_down_answers_with_text():
    retriever = FakeRetriever(error=DependencyUnavailableError("qdrant", "connection refused"))

    answer = await SearchSddKnowledge().execute({"query": "x"}, ToolContext(retriever, None))

    assert answer.startswith("Lỗi:") and "kho dữ liệu SDD" in answer


async def test_full_spec_returns_the_whole_markdown():
    docs = FakeDocuments({"SPC-2": SpecDocument("SPC-2", "Luồng thanh toán", "# 1. Tổng quan\n```sql\nUPDATE x;\n```")})

    answer = await GetFullSpecContent().execute({"spec_id": "SPC-2"}, ToolContext(None, docs))

    assert "SPC-2 — Luồng thanh toán" in answer and "```sql\nUPDATE x;\n```" in answer


async def test_full_spec_of_an_unknown_id_says_it_does_not_exist():
    answer = await GetFullSpecContent().execute({"spec_id": "SPC-999"}, ToolContext(None, FakeDocuments()))

    assert "Không tìm thấy spec SPC-999" in answer


def test_the_descriptions_tell_the_model_when_to_use_each_tool():
    assert "ĐẦU TIÊN" in SearchSddKnowledge().description
    assert "ĐÃ BIẾT CHẮC CHẮN" in GetFullSpecContent().description


async def test_search_results_carry_the_document_titles_for_citations():
    results = [SearchResult(text="API nội bộ", score=0.75, source="vector", spec_ids=["SPC-3"])]
    docs = FakeDocuments({"SPC-3": SpecDocument("SPC-3", "Đăng ký tài khoản và email chào mừng", "...")})

    answer = await SearchSddKnowledge().execute({"query": "q"}, ToolContext(FakeRetriever(results), docs))

    assert "(SPC-3 «Đăng ký tài khoản và email chào mừng», vector, 0.75)" in answer


def test_the_sources_of_tool_results_are_read_back_from_their_text():
    from personal_kb.tools.sdd_knowledge import sources_in

    full = "SPC-2 — Luồng thanh toán đơn hàng\n\n---\nid: SPC-2\n---"
    search = (
        "Kết quả tra cứu SDD cho: q\n\n"
        "[1] (SPC-3 «Đăng ký tài khoản», graph, 0.79)\ntext\n\n"
        "[2] (SPC-5, vector, 0.40)\nx"
    )

    assert sources_in(full) == {"SPC-2": "Luồng thanh toán đơn hàng"}
    assert sources_in(search) == {"SPC-3": "Đăng ký tài khoản", "SPC-5": "SPC-5"}


async def test_a_long_multi_part_query_is_sent_back_to_be_split_instead_of_searched():
    retriever = FakeRetriever(results=[SearchResult(text="x", score=0.9, source="vector", spec_ids=["SPC-1"])])
    scenario = "Kịch bản: chị Hà đăng ký bằng gmail, nhập sai mật khẩu 5 lần, thanh toán đơn qua VNPay. " * 3

    out = await SearchSddKnowledge().execute({"query": scenario}, ToolContext(retriever, None))

    assert out.startswith("Lỗi:") and "tách" in out
    assert retriever.queries == []


async def test_a_short_query_is_searched():
    retriever = FakeRetriever(results=[])

    await SearchSddKnowledge().execute({"query": "IPN VNPay gửi 2 lần"}, ToolContext(retriever, None))

    assert retriever.queries == ["IPN VNPay gửi 2 lần"]


async def test_the_catalog_lists_every_spec_with_its_title_and_owner_but_no_content():
    from personal_kb.tools.sdd_knowledge import ListSddSpecs

    class Catalog(FakeDocuments):
        async def all(self):
            return sorted(self.docs.values(), key=lambda d: d.spec_id)

    docs = Catalog(
        {
            "SPC-2": SpecDocument(
                "SPC-2", "Luồng thanh toán đơn hàng", "---\nid: SPC-2\nowner: Trần Quốc Bảo\n---\nVNPay"
            ),
            "SPC-1": SpecDocument("SPC-1", "Luồng đăng nhập", "---\nid: SPC-1\n---\nArgon2id"),
        }
    )

    out = await ListSddSpecs().execute({}, ToolContext(None, docs))

    assert "- SPC-1: Luồng đăng nhập\n- SPC-2: Luồng thanh toán đơn hàng (người viết: Trần Quốc Bảo)" in out
    assert "VNPay" not in out and "Argon2id" not in out
    assert sources_in(out) == {}  # a listed spec is not a source of the answer


async def test_an_empty_catalog_says_so():
    from personal_kb.tools.sdd_knowledge import ListSddSpecs

    class Empty(FakeDocuments):
        async def all(self):
            return []

    assert await ListSddSpecs().execute({}, ToolContext(None, Empty())) == "Kho SDD chưa có tài liệu nào."


def test_each_tool_says_what_it_is_doing_with_its_arguments():
    from personal_kb.tools.sdd_knowledge import GetFullSpecContent, SearchSddKnowledge, VerifyCitation

    assert SearchSddKnowledge().status_text({"query": "IPN VNPay"}) == "🔍 Đang tìm kiếm trong kho Spec: “IPN VNPay”..."
    assert GetFullSpecContent().status_text({"spec_id": "SPC-2"}) == "📄 Đang đọc tài liệu SPC-2..."
    assert GetFullSpecContent().status_text({}) == "📄 Đang đọc tài liệu ..."  # a missing argument stays empty
    assert VerifyCitation().status_text({"spec_id": "HR-M05"}) == "🔎 Đang đối soát đoạn trích với tài liệu HR-M05..."


async def test_verify_citation_validates_exact_and_multiline_quotes():
    docs = FakeDocuments(
        {
            "HR-M05": SpecDocument(
                "HR-M05",
                "Quy định chấm công và tính lương",
                (
                    "---\nid: HR-M05\ntitle: Quy định chấm công và tính lương\n"
                    "owner: Ryan Truong\nstatus: active\n---\n"
                    "# 1. Tổng quan\n"
                    "Thời gian làm việc tiêu chuẩn là 8 giờ mỗi ngày.\n\n"
                    "## 1.2 Làm thêm giờ\n"
                    "Mức lương làm thêm giờ vào ngày nghỉ là 200% tiền lương giờ thực trả."
                ),
            )
        }
    )
    ctx = ToolContext(retriever=None, documents=docs)
    tool = VerifyCitation()

    # Match across whitespace and newlines
    out = await tool.execute(
        {"spec_id": "HR-M05", "quote": "Mức lương làm thêm giờ vào ngày nghỉ là 200%"},
        ctx,
    )
    assert "✅ XÁC THỰC THÀNH CÔNG" in out
    assert "Mục chứa trích dẫn: ## 1.2 Làm thêm giờ" in out
    assert sources_in(out) == {"HR-M05": "Quy định chấm công và tính lương"}

    # Mismatch
    mismatch = await tool.execute(
        {"spec_id": "HR-M05", "quote": "Mức lương làm thêm giờ là 500% tiền lương"},
        ctx,
    )
    assert "⚠️ CẢNH BÁO: Không tìm thấy đoạn trích" in mismatch

    # Spec not found
    not_found = await tool.execute(
        {"spec_id": "SPC-999", "quote": "Bất kỳ đoạn trích nào"},
        ctx,
    )
    assert "❌ THẤT BẠI: Tài liệu 'SPC-999' không tồn tại" in not_found


async def test_search_warns_the_agent_when_the_results_were_not_reranked():
    unranked = [SearchResult(text="t", score=0.5, source="vector", spec_ids=["SPC-1"], reranked=False)]

    answer = await SearchSddKnowledge().execute({"query": "q"}, ToolContext(FakeRetriever(unranked), None))

    assert answer.startswith("⚠️ Reranker")
