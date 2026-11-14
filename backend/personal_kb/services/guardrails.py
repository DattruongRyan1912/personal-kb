"""Input guardrail in front of the agent (issue 2.4): a fast keyword check, no model call.

Off-topic requests (poems, politics) and prompt-injection phrases ("bỏ qua lệnh trước đó", "ignore all previous
instructions", "you are now …") are refused before the question reaches the graph, so they cost no tokens and never
enter the session memory. Text is compared without Vietnamese diacritics, so "bo qua lenh" is caught too. Patterns
are specific on purpose: "bỏ qua bước xác thực" or "chính sách" are ordinary questions.
"""

import re

from personal_kb.services.graph_models import to_snake

REFUSAL = (
    "Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về hệ thống và tài liệu đặc tả (SDD) của công ty. "
    "Bạn có thể hỏi về nghiệp vụ, API, bảng dữ liệu hoặc quy trình."
)

# matched against the snake_case ASCII form of the question: "Bỏ qua lệnh!" -> "bo_qua_lenh"
_BLOCKED = {
    # "tho" must end the word: "viết thông báo" is a question about the specs
    "off-topic: poetry": r"(lam|viet)_(mot_)?(bai_)?tho(_|$)|write_a_poem|compose_a_poem",
    "off-topic: politics": r"chinh_tri|politic",
    "off-topic: jokes": r"tell_(me_)?a_joke|ke_chuyen_cuoi|stand_up_comedian",
    "prompt injection: drop instructions": (
        r"bo_qua_(moi_|tat_ca_|toan_bo_|cac_)?(lenh|chi_dan|huong_dan|quy_tac)"
        r"|quen_het|quen_(moi_|tat_ca_|toan_bo_)?(lenh|chi_dan|huong_dan)"
        r"|(ignore|forget)_(all_|any_|the_|your_)?(previous|prior|above)_(instructions|prompts|rules)"
        r"|disregard_(all_|the_)?(previous|prior|above)"
    ),
    # "dan" alone is Vietnamese without diacritics ("hướng dẫn"): only the jailbreak's own phrasings
    "prompt injection: role change": (
        r"you_are_now|from_now_on_you|pretend_to_be|act_as_(a|an)_|developer_mode"
        r"|you_are_dan|dan_mode|do_anything_now|tu_(gio|bay_gio)_(tro_di_)?ban_(la|se_la)_"
    ),
    "prompt injection: prompt leak": r"system_prompt|your_(instructions|prompt)",
}
_PATTERNS = {reason: re.compile(rf"(^|_)({pattern})") for reason, pattern in _BLOCKED.items()}


def blocked_reason(question: str) -> str | None:
    """Why the question is refused, or None when it may go to the agent."""
    text = to_snake(question)
    for reason, pattern in _PATTERNS.items():
        if pattern.search(text):
            return reason
    return None
