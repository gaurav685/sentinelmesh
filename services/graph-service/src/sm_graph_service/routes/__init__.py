"""HTTP routes for graph-service: health + metrics + the internal graph-query API.
No ingest — the write path is the Kafka consumer."""

from __future__ import annotations

from . import graph, health, metrics

__all__ = ["graph", "health", "metrics"]
