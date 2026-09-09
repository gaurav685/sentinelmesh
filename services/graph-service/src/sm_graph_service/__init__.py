"""SentinelMesh graph-service.

Phase 4: the only write path into Neo4j. Consumes `graph.commands` (group
`graph-writer`), applies each `GraphCommandPayload` as a parameterized, idempotent
MERGE against the locked graph model, and emits `graph.events`. Labels and
relationship types are validated against the `sm_contracts` allowlist before any
Cypher is built (Cypher cannot parameterize them). Poison commands go to
`graph.commands.dlq`; a Neo4j outage retries rather than drops.

The read-query API (parameterized, tenant-scoped, depth-bounded) is Unit 3.
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
