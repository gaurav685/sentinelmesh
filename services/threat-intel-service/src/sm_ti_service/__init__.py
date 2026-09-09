"""SentinelMesh threat-intelligence service (req 9, TB-4).

IOC store of record (`threat_indicator` / `threat_actor` / `ti_campaign` /
`ti_source`), an enrichment API, and provider-failure tolerance. Nothing here is
fabricated: every indicator carries a `Provenance`, a malformed value is
rejected, and freshness is derived (not asserted). Deterministic local test data
is labelled `source_kind = FIXTURE`.

Produces `TiUpdatePayload` on `ti.updates` (add / update / expire). A background
sweep marks indicators past `expires_at` and announces them once.
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
