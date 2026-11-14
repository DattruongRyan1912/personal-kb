"""Technical names in answers, checked against the specs the tools returned (issue 2.4).

Asked about a case its specs leave open, a small model fills the gap with something plausible: an error code
(UNAUTHORIZED_ROLE_CHANGE), an HTTP status ("trả 401"), a status value (`REFUNDED`), an endpoint, a table. Whether a
spec states such a name can be looked up in the text, so every one the answer uses must appear in what the tools
returned, this turn or earlier in the history, or in the user's own words. A name no spec has is caught; one a spec
has but for another case (401 for an unverified login, where the spec gives it for a wrong password) is not.
"""

import re
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from personal_kb.services.citations import NOT_EVIDENCE, cited_spec_ids

_CONSTANT = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")  # INVALID_CREDENTIALS
_ENDPOINT = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+(/[\w/{}:.-]*[\w}])")
_PATH = re.compile(r"/api/[\w/{}:.-]*[\w}]")
_TABLE = re.compile(r"\b(?:bảng|table)\s+`([a-z][a-z0-9_]*)`", re.IGNORECASE)
_HTTP = re.compile(
    r"\b(?:HTTP|mã|lỗi|trả về|trả|status)\s*(?:HTTP\s*)?([1-5]\d\d)\b"
    r"|\b([1-5]\d\d)\s+(?:OK|Created|Accepted|No Content|Bad Request|Unauthorized|Forbidden|Not Found|Conflict"
    r"|Unprocessable|Too Many Requests|Internal Server Error)\b",
    re.IGNORECASE,
)
_CODE_VALUE = re.compile(r"\b(\w+Code)\s*[=:]\s*['\"]?(\w+)")  # RspCode = 02
_INLINE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_NAME = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[._][A-Za-z0-9]+)+\b")  # in code: users.status, email_outbox
_STATUS = re.compile(r"\b[A-Z]{4,}\b")  # in code written in capitals only: PENDING, PENDING → PAID
_GENERIC = {"HTTP", "HTTPS", "JSON", "UUID", "NULL", "TRUE", "FALSE"}  # formats and literals, not facts of a spec


def claimed_terms(text: str) -> list[str]:
    """The technical names an answer states as facts: error codes, HTTP statuses, code values such as RspCode,
    endpoints, tables, and, written as code, columns and status values. Cited spec ids are the citation check's."""
    terms = [*_CONSTANT.findall(text), *_ENDPOINT.findall(text), *_PATH.findall(text), *_TABLE.findall(text)]
    terms += [code for pair in _HTTP.findall(text) for code in pair if code]
    terms += [f"{name} = {value}" for name, value in _CODE_VALUE.findall(text)]
    for code in _INLINE.findall(text):
        terms += _NAME.findall(code)
        if not re.search(r"[a-z]", code):
            terms += [word for word in _STATUS.findall(code) if word not in _GENERIC]
    cited = set(cited_spec_ids(text))
    return [term for term in dict.fromkeys(terms) if term not in cited]


def unsupported_terms(answer: AIMessage, context: Sequence[BaseMessage]) -> list[str]:
    """The names the answer uses that neither a tool result nor the user's words contain: likely invented.

    As for citations, the session summary, earlier answers and the spec catalog back nothing (they may be wrong, or
    list specs without what they say); the question does, since an answer may repeat the user's own words.
    """
    backing = "\n".join(
        str(m.content)
        for m in context
        if m is not answer
        and (isinstance(m, HumanMessage) or (isinstance(m, ToolMessage) and m.name not in NOT_EVIDENCE))
    )
    return [term for term in claimed_terms(str(answer.content)) if not _stated(term, backing)]


def _stated(term: str, text: str) -> bool:
    """A column named with its table (users.deleted_at) is stated when the spec lists both, as data dictionaries do."""
    parts = term.split(".")
    if len(parts) == 2 and all(re.fullmatch(r"\w+", part) for part in parts):
        return _present(term, text) or all(_present(part, text) for part in parts)
    return _present(term, text)


def _present(term: str, text: str) -> bool:
    """The term as a whole word, any spacing and case: "RspCode=02" is in "trả `RspCode = 02`", PENDING is not in
    PENDING_VERIFICATION."""
    pattern = r"\s*".join(map(re.escape, term.split()))
    if term[0].isalnum():
        pattern = r"(?<!\w)" + pattern
    if term[-1].isalnum():
        pattern += r"(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None
