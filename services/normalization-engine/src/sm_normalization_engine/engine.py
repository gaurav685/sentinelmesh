"""The domain handler: `telemetry.raw` record -> `events.canonical`.

`NormalizationEngine.handle` is wrapped by `sm_common.bus.RecordProcessor`, which
owns the retry / DLQ policy (event-model.md §4/§5). This handler only signals
intent:

- bad JSON / unknown `event_type` / invalid envelope / mapper failure ->
  `PoisonError` (the processor dead-letters it).
- a failed produce to `events.canonical` -> `TransientError` (retried, then
  dead-lettered).

The canonical `event_id` is `uuid5` of the raw `event_id`, so an at-least-once
redelivery re-emits the identical id and downstream `event_id` dedup suppresses
the duplicate.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from aiokafka.structs import ConsumerRecord
from pydantic import ValidationError

from sm_common.bus import EventBusProducer, PoisonError, TransientError
from sm_common.clock import utcnow
from sm_common.observability import Metrics
from sm_contracts import (
    EVENT_PAYLOAD_REGISTRY,
    CanonicalEventPayload,
    EventEnvelope,
    EventType,
    make_partition_key,
)

from .enrich import Enricher, run_enrichers
from .metrics import NormalizationMetrics
from .normalize import UnknownEventTypeError, normalize
from .topics import CANONICAL_TOPIC
from .version import PRODUCER

__all__ = ["NormalizationEngine", "canonical_event_id"]

_log = structlog.get_logger("sm.normalization.engine")

_CANONICAL_NS = uuid.UUID("6f1c3a4e-2b8d-5c7a-9e0f-1a2b3c4d5e6f")


def canonical_event_id(raw_event_id: uuid.UUID) -> uuid.UUID:
    """Deterministic `event_id` for the canonical event derived from one raw
    event (event-model.md §4 idempotency)."""
    return uuid.uuid5(_CANONICAL_NS, f"canonical:{raw_event_id}")


class NormalizationEngine:
    def __init__(
        self,
        *,
        producer: EventBusProducer,
        consumer_group: str,
        metrics: Metrics,
        norm_metrics: NormalizationMetrics,
        enrichers: tuple[Enricher, ...] = (),
        canonical_topic: str = CANONICAL_TOPIC,
    ) -> None:
        self._producer = producer
        self._group = consumer_group
        self._metrics = metrics
        self._m = norm_metrics
        self._enrichers = enrichers
        self._canonical_topic = canonical_topic

    async def handle(self, record: ConsumerRecord) -> None:
        raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")

        try:
            doc: Any = json.loads(raw)
            event_type = EventType(doc["event_type"])
        except (ValueError, TypeError, KeyError) as exc:
            raise PoisonError(f"unparseable telemetry.raw record: {exc!r}") from exc

        payload_model = EVENT_PAYLOAD_REGISTRY.get(event_type)
        if payload_model is None:
            raise PoisonError(f"unknown event_type {event_type.value!r}")

        try:
            envelope = EventEnvelope[payload_model].model_validate(doc)  # type: ignore[valid-type]
        except ValidationError as exc:
            raise PoisonError(f"envelope invalid: {exc}") from exc

        self._m.consumed_inc(event_type.value)

        try:
            canonical = normalize(envelope)
        except UnknownEventTypeError as exc:
            raise PoisonError(str(exc)) from exc
        except Exception as exc:  # a mapper bug — do not wedge the partition
            _log.exception("normalize_failed", event_type=event_type.value)
            raise PoisonError(f"normalize failed: {exc!r}") from exc

        enrichment = await run_enrichers(canonical, self._enrichers)
        if enrichment:
            canonical = canonical.model_copy(update={"enrichment": enrichment})

        out = self._wrap(envelope, canonical)
        try:
            await self._producer.send(
                self._canonical_topic,
                key=out.partition_key,
                value=out.model_dump_json().encode("utf-8"),
            )
        except Exception as exc:
            raise TransientError(f"produce to {self._canonical_topic} failed: {exc!r}") from exc
        self._m.produced_inc(event_type.value)

    def _wrap(
        self, source: EventEnvelope[Any], canonical: CanonicalEventPayload
    ) -> EventEnvelope[CanonicalEventPayload]:
        primary = canonical.actor or canonical.target or (
            canonical.entities[0] if canonical.entities else None
        )
        partition_key = make_partition_key(
            source.tenant_id, primary.value if primary else "unknown"
        )
        return EventEnvelope[CanonicalEventPayload](
            event_id=canonical_event_id(source.event_id),
            event_type=EventType.event_canonical,
            event_version=1,
            occurred_at=source.occurred_at,
            ingested_at=utcnow(),
            producer=PRODUCER,
            tenant_id=source.tenant_id,
            source=source.source,
            correlation_id=source.correlation_id,
            trace_id=source.trace_id,
            partition_key=partition_key,
            payload=canonical,
            metadata={"raw_event_id": str(source.event_id)},
        )
