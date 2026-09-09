"""Neo4j graph store access (ADR-007).

`Graph` wraps one async Neo4j driver: connection management, the configured
query timeout, and parameterized read / write helpers. It does **not** enforce
tenant scoping or the label allowlist — that is the graph repository's job
(`services/graph-service`).

`apply_pending` runs the versioned Cypher schema migrations under
`migrations/neo4j/`.
"""

from __future__ import annotations

from .driver import Graph, GraphUnavailableError
from .migrate import MIGRATIONS_DIR, apply_pending, pending_versions, split_statements

__all__ = [
    "MIGRATIONS_DIR",
    "Graph",
    "GraphUnavailableError",
    "apply_pending",
    "pending_versions",
    "split_statements",
]
