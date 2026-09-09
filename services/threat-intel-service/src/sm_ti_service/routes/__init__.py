"""HTTP routes for threat-intel-service."""

from __future__ import annotations

from . import health, metrics, ti

__all__ = ["health", "metrics", "ti"]
