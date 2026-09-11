"""HTTP routes for simulation-service: health, metrics, scenarios, deception."""

from __future__ import annotations

from . import deception, health, metrics, scenarios

__all__ = ["deception", "health", "metrics", "scenarios"]
