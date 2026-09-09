"""HTTP routes for the ingestion gateway."""

from __future__ import annotations

from . import health, ingest, metrics

__all__ = ["health", "ingest", "metrics"]
