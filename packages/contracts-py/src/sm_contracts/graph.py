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
    "GRAPH_PAYLOADS",
    "GraphCommandPayload",
    "GraphOp",
    "graph_command_id",
]

_GRAPH_CMD_NS = uuid.UUID("b7d2f1a0-3c4e-5d6a-8b9c-0e1f2a3b4c5d")


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


GRAPH_PAYLOADS: dict[EventType, type[SmBaseModel]] = {
    EventType.graph_command: GraphCommandPayload,
}

EVENT_PAYLOAD_REGISTRY.update(GRAPH_PAYLOADS)
