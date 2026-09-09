"""SentinelMesh detection engine (reqs 5, 8).

    telemetry -> features -> anomaly score -> evidence -> detection -> alert

Consumes `events.canonical`; system of record for Postgres `detection` /
`anomaly` / `threat_score` / `security_alert`; emits `detections`. Scores on a
per-(tenant, kind) rolling-window statistical detector (adaptive thresholds) plus
an optional `ml-inference` contribution — a missing model degrades the score
(ADR-013), never drops the detection. Every detection is grounded in
`EvidenceItem`s; no attack conclusion is fabricated and no detection capability
is overclaimed.
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
