"""Feed a scenario's synthetic events into the real telemetry pipeline.

Each `SimEvent` is mapped to the telemetry payload it best resembles and wrapped
in an `EventEnvelope` with `source.type = SourceType.simulation` — so every
downstream consumer (normalization, detection, correlation, graph) can tell a
drill from real traffic. Nothing here is produced anywhere except the one
`telemetry.raw` topic `ingestion-gateway` also writes to; there is no path from
a simulation event into any other system.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sm_common.bus import EventBusProducer
from sm_common.clock import utcnow
from sm_common.ids import new_correlation_id, uuid7
from sm_common.observability import current_trace_id
from sm_contracts import (
    AuthEventPayload,
    AuthOutcome,
    EventEnvelope,
    EventSource,
    EventType,
    FileAccessPayload,
    FileAction,
    NetworkFlowPayload,
    ProcessExecPayload,
    SourceType,
    make_partition_key,
    topic_for_event_type,
)
from sm_ml.scenario import SimEvent, SimEventKind, SyntheticEnvironment

from .version import SERVICE_NAME

__all__ = ["feed_events"]

_RAW_TOPIC = topic_for_event_type(EventType.telemetry_network_flow)
_PRODUCER = f"{SERVICE_NAME}@0.1.0"
_FALLBACK_IP = "10.99.0.1"

_ENVELOPE_BY_TYPE: dict[EventType, type[EventEnvelope[Any]]] = {
    EventType.telemetry_auth_event: EventEnvelope[AuthEventPayload],
    EventType.telemetry_process_exec: EventEnvelope[ProcessExecPayload],
    EventType.telemetry_file_access: EventEnvelope[FileAccessPayload],
    EventType.telemetry_network_flow: EventEnvelope[NetworkFlowPayload],
}

_FILE_ACTIONS = {"read": FileAction.read, "write": FileAction.write, "create": FileAction.create}


def _name_of(env: SyntheticEnvironment, entity_id: str, default: str) -> str:
    e = env.get(entity_id)
    return e.name if e is not None else default


def _to_payload(ev: SimEvent, env: SyntheticEnvironment, at: datetime) -> tuple[EventType, Any] | None:
    if ev.kind in (SimEventKind.auth_failed, SimEventKind.auth_success):
        actor = env.get(ev.actor)
        source_ip = actor.name if actor is not None and actor.kind.value == "ip" else None
        source_host = actor.name if actor is not None and actor.kind.value == "host" else None
        outcome = AuthOutcome.success if ev.kind is SimEventKind.auth_success else AuthOutcome.failure
        return EventType.telemetry_auth_event, AuthEventPayload(
            occurred_at=at, outcome=outcome, auth_type="network",
            principal=_name_of(env, ev.target, ev.target),
            source_host=source_host, source_ip=source_ip,
            failure_reason=ev.attributes.get("reason") if outcome is AuthOutcome.failure else None,
        )
    if ev.kind is SimEventKind.process_exec:
        return EventType.telemetry_process_exec, ProcessExecPayload(
            occurred_at=at, host=_name_of(env, ev.actor, ev.actor),
            process_name=ev.attributes.get("cmd", ev.target)[:256],
        )
    if ev.kind is SimEventKind.file_access:
        actor = env.get(ev.actor)
        host = actor.name if actor is not None and actor.kind.value == "host" else _FALLBACK_IP
        user = actor.name if actor is not None and actor.kind.value == "identity" else None
        action = _FILE_ACTIONS.get(ev.attributes.get("op", "read"), FileAction.read)
        return EventType.telemetry_file_access, FileAccessPayload(
            occurred_at=at, host=host, path=f"/sim/{ev.target}", action=action, user=user,
        )
    if ev.kind is SimEventKind.network_flow:
        src = env.get(ev.actor)
        dst = env.get(ev.target)
        src_ip = src.name if src is not None and src.kind.value == "ip" else _FALLBACK_IP
        dst_ip = dst.name if dst is not None and dst.kind.value == "ip" else _FALLBACK_IP
        return EventType.telemetry_network_flow, NetworkFlowPayload(
            occurred_at=at, src_ip=src_ip, dst_ip=dst_ip, protocol="tcp",
        )


async def feed_events(
    producer: EventBusProducer,
    tenant_id: UUID,
    scenario_id: str,
    events: tuple[SimEvent, ...],
    env: SyntheticEnvironment,
) -> int:
    """Produce every mappable event onto `telemetry.raw`. Returns the count
    actually sent (an unmappable event kind is skipped, not fatal)."""
    base = utcnow()
    sent = 0
    for ev in events:
        at = base.replace(tzinfo=UTC) if base.tzinfo is None else base
        mapped = _to_payload(ev, env, at)
        if mapped is None:
            continue
        event_type, payload = mapped
        envelope_cls = _ENVELOPE_BY_TYPE[event_type]
        envelope = envelope_cls(
            event_id=uuid7(), event_type=event_type, event_version=1,
            occurred_at=at, ingested_at=utcnow(), producer=_PRODUCER, tenant_id=tenant_id,
            source=EventSource(type=SourceType.simulation),
            correlation_id=new_correlation_id(),
            trace_id=current_trace_id(),
            partition_key=make_partition_key(str(tenant_id), scenario_id),
            payload=payload, metadata={"scenario_id": scenario_id, "sim_step": str(ev.step)},
        )
        await producer.send(
            _RAW_TOPIC, key=envelope.partition_key, value=envelope.model_dump_json().encode("utf-8")
        )
        sent += 1
    return sent
