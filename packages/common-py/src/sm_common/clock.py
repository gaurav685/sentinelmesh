"""Time source.

All SentinelMesh code takes "now" from here so tests can freeze it and so we
never accidentally use a naive or local-time value.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["utcnow"]


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)
