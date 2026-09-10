"""HTTP routes for the API gateway."""

from __future__ import annotations

from . import admin, auth, health, metrics, soc

__all__ = ["admin", "auth", "health", "metrics", "soc"]
