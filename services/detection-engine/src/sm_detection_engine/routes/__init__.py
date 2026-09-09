"""HTTP routes for detection-engine (health + metrics only; no ingest)."""

from __future__ import annotations

from . import health, metrics

__all__ = ["health", "metrics"]
