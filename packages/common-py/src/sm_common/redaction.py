"""Secret redaction.

Applied to every log record (structlog processor) and to any error payload
before it leaves the process. Engineering Constitution §5, §18: passwords,
tokens, API keys, and connection strings must never appear in logs or responses.

Redaction is best-effort defense-in-depth, not a licence to log secrets and rely
on this. Two layers:
- key-based: a mapping value whose key looks sensitive is replaced wholesale.
- pattern-based: known secret shapes inside free text are masked.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["REDACTED", "looks_sensitive", "redact"]

REDACTED = "***REDACTED***"

_SENSITIVE_KEY_RE = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|authorization|auth|credential|"
    r"signing[_-]?key|private[_-]?key|session|cookie|access[_-]?key)",
    re.IGNORECASE,
)

# Free-text patterns: bearer tokens, "password=..." in DSNs/URLs, JWT-looking blobs.
_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*[^\s,;'\"]+"),
    re.compile(r"://[^:/@\s]+:([^@\s]+)@"),  # user:pass@host
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),  # JWT
)

_MAX_DEPTH = 8


def looks_sensitive(key: str) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(key))


def _redact_text(text: str) -> str:
    out = text
    for pat in _TEXT_PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: m.group(0).replace(m.group(1), REDACTED), out)
        else:
            out = pat.sub(REDACTED, out)
    return out


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return a redacted copy of `value` (dicts, lists, tuples, strings handled)."""
    if _depth > _MAX_DEPTH:
        return value
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {
            k: (REDACTED if isinstance(k, str) and looks_sensitive(k) else redact(v, _depth=_depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        red = [redact(v, _depth=_depth + 1) for v in value]
        return type(value)(red) if isinstance(value, tuple) else red
    return value
