"""graph-update-emitter (event-model.md §7).

One `events.canonical` event → a small set of `GraphCommandPayload`:

- `MERGE_NODE` for the `actor`, the `target`, and every other entity, so the
  graph has the node before an edge references it.
- `MERGE_EDGE` `actor -[<REL>]-> target`, where `<REL>` comes from the canonical
  `kind` (`data-model.md` relationship vocabulary).

Every command's `command_id` (and the envelope `event_id`) is deterministic in
the source canonical `event_id`, so an at-least-once redelivery re-emits the
identical id and `graph-writer` (Phase 4) dedups it. No state is kept — this job
is a pure map, not a Flink-class stateful operator.
"""

from __future__ import annotations

from typing import Any

from sm_common.clock import utcnow
from sm_common.context import get_correlation_id
from sm_common.ids import new_correlation_id
from sm_contracts import (
    CanonicalEventPayload,
    CanonicalKind,
    EntityKind,
    EntityRef,
    EventEnvelope,
    EventType,
    GraphCommandPayload,
    GraphEndpoint,
    GraphOp,
    graph_command_id,
    make_partition_key,
)

from .version import PRODUCER

__all__ = ["emit"]

# EntityKind -> (Neo4j label, key property name)   (data-model.md §Node labels)
_LABEL: dict[EntityKind, tuple[str, str]] = {
    EntityKind.identity: (":Identity", "identity_id"),
    EntityKind.host: (":Host", "host_id"),
    EntityKind.ip: (":IpAddress", "ip"),
    EntityKind.domain: (":Domain", "fqdn"),
    EntityKind.process: (":Process", "process_id"),
    EntityKind.file: (":File", "file_id"),
}

# CanonicalKind -> relationship type   (data-model.md §Relationship types)
_REL: dict[CanonicalKind, str] = {
    CanonicalKind.network_flow: "CONNECTED_TO",
    CanonicalKind.auth: "AUTHENTICATED_TO",
    CanonicalKind.dns: "RESOLVED",
    CanonicalKind.process_exec: "EXECUTED",
    CanonicalKind.file_access: "ACCESSED",
}


def _endpoint(ref: EntityRef) -> GraphEndpoint:
    label, key_prop = _LABEL[ref.kind]
    return GraphEndpoint(label=label, key={key_prop: ref.value})


def _envelope(
    source: EventEnvelope[CanonicalEventPayload], payload: GraphCommandPayload, primary: str
) -> EventEnvelope[GraphCommandPayload]:
    return EventEnvelope[GraphCommandPayload](
        event_id=payload.command_id,
        event_type=EventType.graph_command,
        event_version=1,
        occurred_at=source.occurred_at,
        ingested_at=utcnow(),
        producer=PRODUCER,
        tenant_id=source.tenant_id,
        source=source.source,
        correlation_id=get_correlation_id() or source.correlation_id or new_correlation_id(),
        trace_id=source.trace_id,
        partition_key=make_partition_key(source.tenant_id, primary),
        payload=payload,
        metadata={"raw_event_id": str(source.payload.raw_event_id)},
    )


def emit(source: EventEnvelope[CanonicalEventPayload]) -> list[EventEnvelope[GraphCommandPayload]]:
    canonical = source.payload
    raw_id = canonical.raw_event_id
    tenant_id = source.tenant_id
    out: list[EventEnvelope[GraphCommandPayload]] = []

    nodes = [e for e in canonical.entities if e.kind in _LABEL]
    for ref in nodes:
        label, key_prop = _LABEL[ref.kind]
        disc = f"{label}:{ref.value}"
        cmd = GraphCommandPayload(
            command_id=graph_command_id(raw_id, GraphOp.merge_node, label, disc),
            op=GraphOp.merge_node,
            tenant_id=tenant_id,
            observed_at=canonical.occurred_at,
            raw_event_id=raw_id,
            label=label,
            key={key_prop: ref.value},
            props={},
        )
        out.append(_envelope(source, cmd, ref.value))

    if canonical.actor and canonical.target and canonical.actor.kind in _LABEL and canonical.target.kind in _LABEL:
        rel = _REL[canonical.kind]
        start, end = _endpoint(canonical.actor), _endpoint(canonical.target)
        disc = f"{start.label}:{canonical.actor.value}->{rel}->{end.label}:{canonical.target.value}"
        edge_props: dict[str, Any] = {"action": canonical.action}
        if canonical.outcome:
            edge_props["outcome"] = canonical.outcome
        for k in ("dst_port", "protocol", "bytes_sent", "auth_type", "query_type"):
            if k in canonical.attributes:
                edge_props[k] = canonical.attributes[k]
        cmd = GraphCommandPayload(
            command_id=graph_command_id(raw_id, GraphOp.merge_edge, rel, disc),
            op=GraphOp.merge_edge,
            tenant_id=tenant_id,
            observed_at=canonical.occurred_at,
            raw_event_id=raw_id,
            label=rel,
            start=start,
            end=end,
            props=edge_props,
        )
        out.append(_envelope(source, cmd, canonical.actor.value))

    return out
