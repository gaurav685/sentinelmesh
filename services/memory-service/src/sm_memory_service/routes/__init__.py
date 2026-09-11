"""HTTP routes for memory-service: health, metrics, memory, prediction."""

from __future__ import annotations

from . import health, memory, metrics, prediction

__all__ = ["health", "memory", "metrics", "prediction"]
