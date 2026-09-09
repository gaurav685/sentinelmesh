"""SentinelMesh ML inference service (ADR-013).

Loads registered anomaly models (`sm_ml.ModelRegistry`) in-process and serves
typed inference over an internal, service-JWT-guarded API. A model that is not
registered, not loadable, or whose serving dependencies are missing returns
`MODEL_UNAVAILABLE` (HTTP 503) — the caller (`detection-engine`) degrades to the
statistical detector (ADR-013). No accuracy or latency target is claimed.
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
