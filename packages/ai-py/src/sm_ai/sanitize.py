"""Prompt-injection scanning and the untrusted-content fence.

Retrieved telemetry, alert text, graph properties, threat-intel notes — anything
that originated outside SentinelMesh's own trusted code — is **data, not
instructions**. `scan_for_injection` flags the well-known override patterns so
the caller can log/deny, and `fence_untrusted` wraps the content in a delimiter
the model is told to treat as inert, with any lookalike delimiter in the content
neutralised so it cannot break out.

This is defence in depth, not a guarantee: the real protection is that the model
has no capability of its own (every tool is separately authorized).
"""

from __future__ import annotations

import re

__all__ = ["FENCE_END", "FENCE_START", "fence_untrusted", "scan_for_injection"]

FENCE_START = "<<<UNTRUSTED_EVIDENCE"
FENCE_END = "UNTRUSTED_EVIDENCE>>>"

# Case-insensitive substring / regex patterns that indicate an attempt to
# redirect the model. Kept deliberately small and specific — a noisy scanner
# that fires on ordinary security prose is useless.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_previous", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts?)", re.I)),
    ("disregard", re.compile(r"disregard\s+(the\s+)?(system|previous|above)", re.I)),
    ("new_instructions", re.compile(r"\bnew\s+instructions?\s*:", re.I)),
    ("role_override", re.compile(r"you\s+are\s+now\s+(a|an|the)\b", re.I)),
    ("system_prefix", re.compile(r"(^|\n)\s*(system|assistant)\s*:", re.I)),
    ("chat_markup", re.compile(r"<\|?(im_start|im_end|system|/?s)\|?>", re.I)),
    ("tool_injection", re.compile(r'"(tool_call|function_call|tool_use)"\s*:', re.I)),
    (
        "exfil_request",
        re.compile(
            r"(print|reveal|repeat|output)\s+(your|the)\s+"
            r"(system\s+prompt|instructions|api[\s_-]?key)",
            re.I,
        ),
    ),
    ("prompt_boundary", re.compile(re.escape(FENCE_START), re.I)),
    ("prompt_boundary_end", re.compile(re.escape(FENCE_END), re.I)),
)


def scan_for_injection(text: str) -> list[str]:
    """Return the names of every injection pattern found in `text` (possibly
    empty). Order is stable."""
    return [name for name, pat in _PATTERNS if pat.search(text)]


def fence_untrusted(label: str, text: str, *, max_chars: int = 20_000) -> str:
    """Wrap `text` as inert evidence. Any fence-delimiter lookalike inside the
    content is broken up; the block is truncated to `max_chars`."""
    safe = text.replace(FENCE_START, "<<<u_e").replace(FENCE_END, "u_e>>>")
    safe = re.sub(r"<\|?(im_start|im_end)\|?>", "<blocked>", safe, flags=re.I)
    if len(safe) > max_chars:
        safe = safe[:max_chars] + "\n…[truncated]"
    clean_label = re.sub(r"[^\w .:/@-]", "", label)[:120]
    return (
        f"{FENCE_START} name={clean_label!r}\n"
        f"{safe}\n"
        f"{FENCE_END}"
    )
