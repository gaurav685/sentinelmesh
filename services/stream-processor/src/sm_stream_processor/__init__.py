"""SentinelMesh stream processor.

Phase 3: the `graph-update-emitter` job — consumes `events.canonical`, emits a
`GraphCommandPayload` per canonical event onto `graph.commands` (idempotent
`command_id`). Poison records go to `events.canonical.dlq`. Stateless; no Flink.
Stateful jobs (feature windows, sessionization) are a later engine (ADR-010).
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
