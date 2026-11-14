from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from personal_kb.services.grounding import claimed_terms, unsupported_terms

SPC_1 = (
    "SPC-1 — Luồng đăng nhập\n\nPOST /api/v1/auth/login\nResponse 200:\n"
    "| 401 | INVALID_CREDENTIALS | Sai email hoặc mật khẩu |\n| 423 | ACCOUNT_LOCKED | Đã sai 5 lần |\n"
    "Bảng ghi `users`, `login_sessions`; `users.failed_login_count` tăng mỗi lần sai."
)
SPC_2 = "SPC-2 — Luồng thanh toán\n\nChỉ khi `payments.status = PENDING`; bản lặp thì trả `RspCode = 02` cho VNPay."


def test_codes_statuses_endpoints_tables_and_columns_are_claimed():
    answer = (
        "Đổi role bị từ chối với `UNAUTHORIZED_ROLE_CHANGE` (trả 401). Request trùng nhận 200 OK. "
        "Đơn chuyển `REFUNDED` qua POST /api/v1/payments/refund, ghi vào bảng `refunds` và `payments.refund_amount`; "
        "VNPay nhận `RspCode = 00`."
    )

    assert claimed_terms(answer) == [
        "UNAUTHORIZED_ROLE_CHANGE",
        "/api/v1/payments/refund",
        "refunds",
        "401",
        "200",
        "RspCode = 00",
        "REFUNDED",
        "payments.refund_amount",
    ]


def test_plain_words_numbers_formats_and_cited_spec_ids_are_not_claimed():
    answer = (
        "Sai 5 lần thì khoá 15 phút, mỗi 10.000 VND cộng 1 điểm; token là JWT, body là `JSON`, "
        "mật khẩu băm bằng `Argon2id`, SĐT `0912345678` [Luồng đăng nhập](SPC-1) [SDD_CORE_002]. Bảng dữ liệu đủ."
    )

    assert claimed_terms(answer) == []


def test_terms_the_specs_read_state_pass_and_invented_ones_are_reported():
    context = [
        HumanMessage("Sai mật khẩu và IPN lặp thì sao?"),
        AIMessage("", tool_calls=[{"id": "c1", "name": "get_full_spec_content", "args": {"spec_id": "SPC-1"}}]),
        ToolMessage(SPC_1, tool_call_id="c1", name="get_full_spec_content"),
        AIMessage("", tool_calls=[{"id": "c2", "name": "get_full_spec_content", "args": {"spec_id": "SPC-2"}}]),
        ToolMessage(SPC_2, tool_call_id="c2", name="get_full_spec_content"),
    ]
    answer = AIMessage(
        "Sai mật khẩu trả 401 `INVALID_CREDENTIALS` qua POST /api/v1/auth/login, tăng `users.failed_login_count`; "
        "đổi role trả `UNAUTHORIZED_ROLE_CHANGE`. IPN lặp: `RspCode=02` khi `payments.status` khác `PENDING`; "
        "lệch tiền trả `RspCode = 04`."
    )

    assert unsupported_terms(answer, context) == ["UNAUTHORIZED_ROLE_CHANGE", "RspCode = 04"]


def test_the_question_backs_a_term_but_the_catalog_summary_and_earlier_answers_do_not():
    context = [
        SystemMessage("Người dùng đã hỏi về ACCOUNT_LOCKED", name="Summary_Context"),
        HumanMessage("Tài khoản ở trạng thái PENDING_VERIFICATION thì đăng nhập được không?"),
        AIMessage("Bị khoá thì trả `USER_SUSPENDED`."),
        AIMessage("", tool_calls=[{"id": "c1", "name": "list_sdd_specs", "args": {}}]),
        ToolMessage("- SPC-1: Luồng đăng nhập (USER_LOCKED)", tool_call_id="c1", name="list_sdd_specs"),
    ]
    answer = AIMessage("`PENDING_VERIFICATION` chưa nói; khoá thì `ACCOUNT_LOCKED`, `USER_LOCKED`, `USER_SUSPENDED`.")

    assert unsupported_terms(answer, context) == ["ACCOUNT_LOCKED", "USER_LOCKED", "USER_SUSPENDED"]


def test_a_column_named_with_its_table_passes_when_the_spec_lists_both():
    data_dictionary = "Từ điển dữ liệu — bảng `users`\n| 1 | id | uuid |\n| 12 | deleted_at | timestamptz |"
    context = [ToolMessage(data_dictionary, tool_call_id="c1")]
    answer = AIMessage("Xoá mềm đặt `users.deleted_at` theo `users.id`, không có `users.archived_at`.")

    assert unsupported_terms(answer, context) == ["users.archived_at"]


def test_a_status_must_appear_as_a_whole_word():
    context = [ToolMessage("Đăng ký tạo user PENDING_VERIFICATION", tool_call_id="c1")]

    assert unsupported_terms(AIMessage("Trạng thái là `PENDING`."), context) == ["PENDING"]
