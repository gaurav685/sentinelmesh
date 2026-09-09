"""SentinelMesh normalization engine.

Consumes `telemetry.raw`, maps each sensor payload to a `CanonicalEventPayload`
(deterministic; enrichment providers are pluggable and not yet implemented),
and produces `events.canonical`. Poison records go to `telemetry.raw.dlq`.
"""

from __future__ import annotations

from .app import build_services, create_app
from .version import API_PREFIX, API_VERSION, SERVICE_NAME, SERVICE_VERSION

__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "build_services",
    "create_app",
]
