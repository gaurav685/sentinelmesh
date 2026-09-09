"""HTTP routes for ml-inference: health, metrics, inference."""

from __future__ import annotations

from . import health, infer, metrics

__all__ = ["health", "infer", "metrics"]
