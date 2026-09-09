"""Emit `ti.updates` for a changed indicator."""

from __future__ import annotations

import uuid

from sm_common.bus import EventBusProducer
from sm_common.clock import utcnow
from sm_common.context import get_correlation_id
from sm_common.ids import new_correlation_id
from sm_contracts import (
    EventEnvelope,
    EventSource,
    EventType,
    SourceType,
    ThreatIndicator,
    TiUpdateAction,
    TiUpdatePayload,
)

from .version import PRODUCER

__all__ = ["PLATFORM_TENANT", "publish_update", "ti_update_envelope"]

# A global (non-tenant) IOC still needs a tenant on the event envelope, which is
# non-null by contract. Consumers read `payload.tenant_id` (nullable) for scope.
PLATFORM_TENANT = uuid.UUID(int=0)


def ti_update_envelope(
    indicator: ThreatIndicator, action: TiUpdateAction
) -> EventEnvelope[TiUpdatePayload]:
    now = utcnow()
    payload = TiUpdatePayload(
        indicator_id=indicator.id, type=indicator.type, value=indicator.value,
        tenant_id=indicator.tenant_id, source=indicator.source, action=action,
        confidence=indicator.confidence, freshness=indicator.freshness, observed_at=now,
    )
    # The `ti.updates` topic is keyed by source (event-model.md §3).
    return EventEnvelope[TiUpdatePayload](
        event_id=indicator.id, event_type=EventType.ti_indicator_updated, event_version=1,
        occurred_at=now, ingested_at=now, producer=PRODUCER,
        tenant_id=indicator.tenant_id or PLATFORM_TENANT,
        source=EventSource(type=SourceType.internal),
        correlation_id=get_correlation_id() or new_correlation_id(),
        partition_key=indicator.source,
        payload=payload, metadata={},
    )


async def publish_update(
    producer: EventBusProducer, indicator: ThreatIndicator, action: TiUpdateAction
) -> None:
    env = ti_update_envelope(indicator, action)
    await producer.send(
        "ti.updates", key=env.partition_key, value=env.model_dump_json().encode("utf-8")
    )
