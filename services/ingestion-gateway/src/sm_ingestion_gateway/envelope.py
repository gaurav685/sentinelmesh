"""Build the canonical `EventEnvelope` for an accepted sensor payload.

The sensor sends only the bare payload. Everything authoritative on the envelope
is set here, server-side:

- `event_id` — a fresh UUIDv7 (the bus idempotency key).
- `tenant_id` — from the authenticated `SensorIdentity`, **never** the body.
- `source` — `type=sensor`, `sensor_id` from the identity.
- `occurred_at` — lifted from the payload's own event time.
- `ingested_at` — now.
- `producer` — `ingestion-gateway@<version>`.
- `partition_key` — `sha256(tenant_id + ':' + primary_entity)[:16]`
  (event-model.md), so all events for one entity stay ordered on one partition
  and the key length is bounded regardless of the entity string.

`build_envelope` raises `pydantic.ValidationError` when the body fails the
payload schema (bad IP, out-of-range port, unknown field, …) or when the
resulting envelope is itself invalid (e.g. the payload's `occurred_at` is more
than five minutes in the future). The caller turns that into `422` + a DLQ write.

Each `event_type` is built as its concrete `EventEnvelope[...]` class, not the
open generic, so `model_dump()` in the sink keeps every payload field.
"""

from __future__ import annotations

from typing import Any, cast

from sm_common.clock import utcnow
from sm_common.context import get_correlation_id
from sm_common.ids import new_correlation_id, uuid7
from sm_common.security import SensorIdentity
from sm_contracts import (
    EventEnvelope,
    EventSource,
    EventType,
    SmBaseModel,
    SourceType,
    make_partition_key,
)
from sm_contracts.telemetry import (
    AuthEventPayload,
    DnsQueryPayload,
    FileAccessPayload,
    NetworkFlowPayload,
    ProcessExecPayload,
)

from .version import PRODUCER

__all__ = ["build_envelope"]

_ENVELOPE_BY_TYPE: dict[EventType, type[EventEnvelope[Any]]] = {
    EventType.telemetry_network_flow: EventEnvelope[NetworkFlowPayload],
    EventType.telemetry_auth_event: EventEnvelope[AuthEventPayload],
    EventType.telemetry_dns_query: EventEnvelope[DnsQueryPayload],
    EventType.telemetry_process_exec: EventEnvelope[ProcessExecPayload],
    EventType.telemetry_file_access: EventEnvelope[FileAccessPayload],
}

# Field on each telemetry payload that identifies the primary entity, so events
# for that entity are ordered relative to each other.
_PARTITION_FIELD: dict[EventType, str] = {
    EventType.telemetry_network_flow: "src_ip",
    EventType.telemetry_auth_event: "principal",
    EventType.telemetry_dns_query: "client_ip",
    EventType.telemetry_process_exec: "host",
    EventType.telemetry_file_access: "host",
}


def _partition_key(tenant_id: str, event_type: EventType, payload: SmBaseModel) -> str:
    field = _PARTITION_FIELD.get(event_type)
    entity = getattr(payload, field, None) if field else None
    return make_partition_key(tenant_id, str(entity) if entity is not None else "unknown")


def build_envelope(
    *,
    event_type: EventType,
    payload_model: type[SmBaseModel],
    raw_payload: Any,
    identity: SensorIdentity,
    client_event_id: str | None = None,
) -> EventEnvelope[Any]:
    payload = payload_model.model_validate(raw_payload)
    occurred_at = cast("Any", payload).occurred_at
    tenant_id = str(identity.tenant_id)

    metadata: dict[str, Any] = {"sensor_type": identity.type.value}
    if client_event_id:
        metadata["client_event_id"] = client_event_id

    envelope_cls = _ENVELOPE_BY_TYPE[event_type]
    return envelope_cls(
        event_id=uuid7(),
        event_type=event_type,
        event_version=1,
        occurred_at=occurred_at,
        ingested_at=utcnow(),
        producer=PRODUCER,
        tenant_id=identity.tenant_id,
        source=EventSource(type=SourceType.sensor, sensor_id=identity.sensor_id),
        correlation_id=get_correlation_id() or new_correlation_id(),
        partition_key=_partition_key(tenant_id, event_type, payload),
        payload=payload,
        metadata=metadata,
    )
