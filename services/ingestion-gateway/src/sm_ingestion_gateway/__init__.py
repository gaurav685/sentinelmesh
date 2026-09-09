"""SentinelMesh ingestion gateway.

Authenticated intake for sensor telemetry. Validates the bare payload a sensor
sends, builds the canonical `EventEnvelope` server-side (tenant and source from
the authenticated sensor identity, never the body), and hands accepted events to
the raw-event sink and malformed ones to the dead-letter sink.
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
