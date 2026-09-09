"""Graph command contract (CONTRACTS.md §5; docs/architecture/data-model.md).

`graph.commands` is the **only** write path into Neo4j. Producers
(`stream-processor`, `detection-engine`) emit `GraphCommandPayload`; `graph-writer`
(Phase 4) applies each with MERGE semantics, idempotent by `command_id`.

A command is deliberately thin: a label (node label or relationship type), a
`key` that identifies the node — or, for `MERGE_EDGE`, both endpoints — and the
`props` to set. `graph-writer` owns the Cypher; this contract only says *what*
to write.

Idempotency: `command_id` is derived deterministically from the source event so
an at-least-once redelivery re-emits the identical id and `graph-writer`'s
`command_id` uniqueness / MERGE suppresses the duplicate.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from .common import SmBaseModel, to_utc
from .events import EVENT_PAYLOAD_REGISTRY, EventType

__all__ = [
    "GRAPH_NODE_KEY",
    "GRAPH_NODE_LABELS",
    "GRAPH_PAYLOADS",
    "GRAPH_REL_TYPES",
    "GraphCommandPayload",
    "GraphEndpoint",
    "GraphEventPayload",
    "GraphMutationOutcome",
    "GraphOp",
    "graph_command_id",
    "graph_node_uid",
    "normalize_label",
]

_GRAPH_CMD_NS = uuid.UUID("b7d2f1a0-3c4e-5d6a-8b9c-0e1f2a3b4c5d")

# --------------------------------------------------------------------------- #
# Neo4j label / relationship allowlist (docs/architecture/data-model.md).
# Cypher cannot parameterize a label or a relationship type, so `graph-writer`
# validates every command's label against these sets before building Cypher.
# Anything not here is dead-lettered — this is the injection guard.
# --------------------------------------------------------------------------- #
GRAPH_NODE_KEY: dict[str, str] = {
    "Tenant": "tenant_id",
    "Identity": "identity_id",
    "Host": "host_id",
    "IpAddress": "ip",
    "Domain": "fqdn",
    "Process": "process_id",
    "File": "file_id",
    "Sensor": "sensor_id",
    "Detection": "detection_id",
    "AttackChain": "chain_id",
    "AttackTechnique": "technique_id",
    "ThreatActor": "actor_id",
    "Campaign": "campaign_id",
}
GRAPH_NODE_LABELS: frozenset[str] = frozenset(GRAPH_NODE_KEY)

GRAPH_REL_TYPES: frozenset[str] = frozenset({
    "AUTHENTICATED_TO", "LOGGED_INTO", "CONNECTED_TO", "RESOLVED", "RESOLVES_TO",
    "EXECUTED", "DOWNLOADED", "SPAWNED", "ACCESSED", "USED_CREDENTIAL_ON",
    "INVOLVES", "HAS_STAGE", "MAPPED_TO", "INCLUDES", "ATTRIBUTED",
})


def normalize_label(label: str) -> str:
    """`':Host'` / `'Host'` -> `'Host'`. Commands carry the `:`-prefixed form."""
    return label.lstrip(":")


def graph_node_uid(tenant_id: UUID, key_value: object) -> str:
    """Synthetic per-tenant node key. Neo4j Community cannot enforce a composite
    `(tenant_id, <key>)` uniqueness constraint, so `graph-service` writes this
    `uid` on every node and the `neo4j/0001` migration puts the UNIQUE
    constraint there. Format: `"<tenant_id>:<natural key value>"`."""
    return f"{tenant_id}:{key_value}"


class GraphOp(StrEnum):
    merge_node = "MERGE_NODE"
    merge_edge = "MERGE_EDGE"
    set_props = "SET_PROPS"
    prune = "PRUNE"


class GraphEndpoint(SmBaseModel):
    """One end of a `MERGE_EDGE` — a node label plus its key."""

    label: str = Field(min_length=1, max_length=64, description="Neo4j label, e.g. ':Host'.")
    key: dict[str, Any] = Field(description="The node's key property, e.g. {'host_id': 'web01'}.")


class GraphCommandPayload(SmBaseModel):
    command_id: UUID = Field(description="Idempotency key; deterministic per source event + command.")
    op: GraphOp
    tenant_id: UUID = Field(description="Becomes a non-null property on every node/edge (data-model invariant).")
    observed_at: datetime = Field(description="Event time from the source event. UTC.")
    raw_event_id: UUID = Field(description="The canonical/detection event this was derived from (lineage).")

    # MERGE_NODE / SET_PROPS / PRUNE: the node.  MERGE_EDGE: the relationship type.
    label: str = Field(min_length=1, max_length=64)
    key: dict[str, Any] = Field(
        default_factory=dict,
        description="For a node op: its key property. For MERGE_EDGE: unused (see start/end).",
    )
    props: dict[str, Any] = Field(default_factory=dict)

    # MERGE_EDGE only.
    start: GraphEndpoint | None = None
    end: GraphEndpoint | None = None

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


def graph_command_id(raw_event_id: UUID, op: GraphOp, label: str, discriminator: str) -> UUID:
    """Deterministic `command_id` for one command derived from one source event.
    `discriminator` is the node key or the edge endpoints, rendered stably."""
    return uuid.uuid5(_GRAPH_CMD_NS, f"{raw_event_id}|{op.value}|{label}|{discriminator}")


# --------------------------------------------------------------------------- #
# graph.events — what `graph-service` did with a command (Phase 4).
# Consumed by api-projection (read model) and notification-fanout.
# --------------------------------------------------------------------------- #
class GraphMutationOutcome(StrEnum):
    applied = "APPLIED"           # the mutation ran (node/edge created or updated)
    duplicate = "DUPLICATE"       # command_id already applied — no-op
    stale = "STALE"               # older than the stored watermark — no-op (out-of-order)


class GraphEventPayload(SmBaseModel):
    command_id: UUID = Field(description="The `graph.commands` command this reports on.")
    op: GraphOp
    outcome: GraphMutationOutcome
    tenant_id: UUID
    observed_at: datetime = Field(description="Event time carried from the command. UTC.")
    raw_event_id: UUID = Field(description="Lineage — the source telemetry/detection event.")
    label: str = Field(min_length=1, max_length=64, description="Node label or relationship type.")
    nodes_written: int = Field(default=0, ge=0)
    relationships_written: int = Field(default=0, ge=0)

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


GRAPH_PAYLOADS: dict[EventType, type[SmBaseModel]] = {
    EventType.graph_command: GraphCommandPayload,
    EventType.graph_event: GraphEventPayload,
}

EVENT_PAYLOAD_REGISTRY.update(GRAPH_PAYLOADS)
