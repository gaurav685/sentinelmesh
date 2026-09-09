"""HTTP routes for the stream processor (health + metrics only)."""

from __future__ import annotations

from . import health, metrics

__all__ = ["health", "metrics"]
