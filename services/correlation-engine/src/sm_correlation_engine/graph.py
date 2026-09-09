"""Project an attack chain onto `graph.commands`.

One updated chain -> a small, deterministic set of `GraphCommandPayload`:

- `MERGE_NODE :AttackChain {chain_id}` with the chain's current summary props.
- `MERGE_EDGE (:AttackChain)-[:INVOLVES]->(<subject node>)` — links the chain to
  the identity / host / ip / domain it is about.
- `MERGE_EDGE (:AttackChain)-[:MAPPED_TO]->(:AttackTechnique {technique_id})` for
  every technique the chain's detections named.

Every `command_id` is deterministic in the chain id + op + label + discriminator,
so an at-least-once redelivery re-emits identical ids and `graph-writer` dedups.
The chain id is used as the `raw_event_id` (lineage) since a chain has no single
source event.
"""

from __future__ import annotations

from sm_common.clock import utcnow
from sm_common.context import get_correlation_id
from sm_common.ids import new_correlation_id
from sm_contracts import (
    AttackChainModel,
    DetectionPayload,
    EventEnvelope,
    EventType,
    GraphCommandPayload,
    GraphEndpoint,
    GraphOp,
    ThreatSubjectType,
    graph_command_id,
    make_partition_key,
)

from .version import PRODUCER

__all__ = ["chain_graph_commands"]

_CHAIN_LABEL = ":AttackChain"

# subject type -> (Neo4j label, key property)   (sm_contracts.GRAPH_NODE_KEY)
_SUBJECT_NODE: dict[ThreatSubjectType, tuple[str, str]] = {
    ThreatSubjectType.identity: (":Identity", "identity_id"),
    ThreatSubjectType.host: (":Host", "host_id"),
    ThreatSubjectType.ip: (":IpAddress", "ip"),
    ThreatSubjectType.domain: (":Domain", "fqdn"),
}


def chain_graph_commands(
    source: EventEnvelope[DetectionPayload], chain: AttackChainModel
) -> list[EventEnvelope[GraphCommandPayload]]:
    chain_id = chain.id
    tenant_id = chain.tenant_id
    key = {"chain_id": str(chain_id)}
    out: list[EventEnvelope[GraphCommandPayload]] = []

    node_props = {
        "tenant_id": str(tenant_id),
        "subject_type": chain.subject_type.value,
        "subject_id": chain.subject_id,
        "status": chain.status.value,
        "score": chain.score,
        "progression": chain.progression,
        "confidence": chain.confidence,
        "score_version": chain.score_version,
        "distinct_stage_count": chain.distinct_stage_count,
        "detection_count": chain.detection_count,
        "ti_corroborated": chain.ti_corroborated,
        "first_seen": chain.first_seen.isoformat(),
        "last_seen": chain.last_seen.isoformat(),
    }
    out.append(_envelope(source, GraphCommandPayload(
        command_id=graph_command_id(chain_id, GraphOp.merge_node, _CHAIN_LABEL, str(key)),
        op=GraphOp.merge_node, tenant_id=tenant_id, observed_at=chain.last_seen,
        raw_event_id=chain_id, label=_CHAIN_LABEL, key=key, props=node_props,
    ), chain.subject_id))

    subject = _SUBJECT_NODE.get(chain.subject_type)
    if subject is not None:
        s_label, s_key_prop = subject
        start = GraphEndpoint(label=_CHAIN_LABEL, key=key)
        end = GraphEndpoint(label=s_label, key={s_key_prop: chain.subject_id})
        disc = f"{_CHAIN_LABEL}:{chain_id}->INVOLVES->{s_label}:{chain.subject_id}"
        out.append(_envelope(source, GraphCommandPayload(
            command_id=graph_command_id(chain_id, GraphOp.merge_edge, "INVOLVES", disc),
            op=GraphOp.merge_edge, tenant_id=tenant_id, observed_at=chain.last_seen,
            raw_event_id=chain_id, label="INVOLVES", start=start, end=end, props={},
        ), chain.subject_id))

    for tid in chain.technique_ids:
        start = GraphEndpoint(label=_CHAIN_LABEL, key=key)
        end = GraphEndpoint(label=":AttackTechnique", key={"technique_id": tid})
        disc = f"{_CHAIN_LABEL}:{chain_id}->MAPPED_TO->:AttackTechnique:{tid}"
        out.append(_envelope(source, GraphCommandPayload(
            command_id=graph_command_id(chain_id, GraphOp.merge_edge, "MAPPED_TO", disc),
            op=GraphOp.merge_edge, tenant_id=tenant_id, observed_at=chain.last_seen,
            raw_event_id=chain_id, label="MAPPED_TO", start=start, end=end, props={},
        ), chain.subject_id))

    return out


def _envelope(
    source: EventEnvelope[DetectionPayload], payload: GraphCommandPayload, primary: str
) -> EventEnvelope[GraphCommandPayload]:
    return EventEnvelope[GraphCommandPayload](
        event_id=payload.command_id, event_type=EventType.graph_command, event_version=1,
        occurred_at=source.occurred_at, ingested_at=utcnow(), producer=PRODUCER,
        tenant_id=source.tenant_id, source=source.source,
        correlation_id=get_correlation_id() or source.correlation_id or new_correlation_id(),
        trace_id=source.trace_id,
        partition_key=make_partition_key(source.tenant_id, primary),
        payload=payload, metadata={"chain_id": str(payload.raw_event_id)},
    )
