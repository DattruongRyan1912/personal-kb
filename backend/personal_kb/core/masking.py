"""Secrets kept out of traces (issue 4.1): Langfuse runs this on everything it records before sending it.

A value under a secret-sounding key (password, token, api_key, authorization…) is replaced whole; in text, API keys,
JWTs, bearer tokens, `NAME_PASSWORD=…` style lines, credentials in URLs and private keys are replaced, and so is any
occurrence of this deployment's own secrets. Spec text and token counts (prompt_tokens, max_tokens) are left alone.
The mask never raises: a value it cannot read is replaced by "[masked]".
"""

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

MASK = "***"
_SECRET_KEY = re.compile(
    r"(?i)^(?:.*[_-])?(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|authorization|cookie|credentials?"
    r"|(?:private|access|secret|service[_-]?role)[_-]?key)$"
)
_TEXT = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[PRIVATE KEY]"),
    (re.compile(r"\b(?:pk|sk)-lf-[A-Za-z0-9-]{8,}"), MASK),  # Langfuse keys
    (re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{16,}"), MASK),  # OpenAI-style keys
    (re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"), MASK),  # JWTs
    (re.compile(r"(?i)\b(bearer\s+)[\w.~+/-]+=*"), r"\g<1>" + MASK),
    (
        re.compile(
            r"(?i)\b(\w*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_KEY|ACCESS_KEY)\w*)(\s*[=:]\s*)"
            r"(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
        ),
        r"\g<1>\g<2>" + MASK,
    ),
    # a password typed in Vietnamese; ":" or "=" only, so "mật khẩu băm Argon2id" in a spec is left alone
    (re.compile(r"(?i)\b(mật\s+khẩu)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"), r"\g<1>\g<2>" + MASK),
    (re.compile(r"\b([a-z][a-z0-9+.-]*://[^:/\s@]*:)[^@\s/]+@"), r"\g<1>" + MASK + "@"),  # user may be empty
]
_MIN_SECRET_LENGTH = 8  # shorter values ("ollama", "neo4j") are too common to replace everywhere


def make_mask(secrets: Iterable[str | None]) -> Callable[..., Any]:
    """The mask for Langfuse(mask=...): secrets are this deployment's own values, replaced wherever they appear."""
    exact = sorted({s for s in secrets if s and len(s) >= _MIN_SECRET_LENGTH}, key=len, reverse=True)

    def text(value: str) -> str:
        for secret in exact:
            value = value.replace(secret, MASK)
        for pattern, replacement in _TEXT:
            value = pattern.sub(replacement, value)
        return value

    def walk(data: Any) -> Any:
        if isinstance(data, str):
            return text(data)
        if isinstance(data, Mapping):
            return {k: MASK if isinstance(k, str) and _SECRET_KEY.match(k) else walk(v) for k, v in data.items()}
        if isinstance(data, list | tuple):
            return type(data)(walk(item) for item in data)
        return data

    def mask(*, data: Any, **_: Any) -> Any:
        try:
            return walk(data)
        except Exception:
            return "[masked]"

    return mask
