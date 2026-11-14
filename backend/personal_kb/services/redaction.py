"""Secret redaction applied to worklog text on write.

KEEP IN SYNC with scripts/project_brief.py (stdlib host script); a test compares both lists.
"""

import re

REDACTIONS = [
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL),
        "[REDACTED]",
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]+"), "Bearer [REDACTED]"),
    (
        re.compile(r"(?i)(\bauthorization[\"']?\s*[:=]\s*[\"']?)Basic\s+[A-Za-z0-9+/=]+"),
        r"\1Basic [REDACTED]",
    ),
    (re.compile(r"\b([a-z][a-z0-9+.\-]*://)[^\s/@]+@"), r"\1[REDACTED]@"),
    (re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED]"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"), "[REDACTED]"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}"), "[REDACTED]"),
    (re.compile(r"\bAQ\.[A-Za-z0-9_\-]{20,}"), "[REDACTED]"),
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_\-.]*(?:password|passwd|token|secret)"
            r"|[A-Za-z0-9_\-.]*?(?:[_\-.]|api|private|access|secret|signing|auth|encryption)key)"
            r"([\"']?\s*[=:]\s*)"
            r"(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
        ),
        r"\1\2[REDACTED]",
    ),
]


def redact(text: str) -> str:
    for pattern, repl in REDACTIONS:
        text = pattern.sub(repl, text)
    return text
