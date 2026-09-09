"""The record handler: `telemetry.raw` record -> `events.canonical`.

`NormalizationEngine.handle` is the `RecordHandler` passed to
`EventBusConsumer.run`. Contract with the consumer wrapper:

- A **poison** record (unparseable, unknown `event_type`, invalid envelope,
  mapper failure) is written to `telemetry.raw.dlq` and `handle` returns
  normally, so the consumer commits the offset and the partition keeps moving
  (event-model.md §4/§5).
- A **produce** failure (the canonical topic or the DLQ topic is unreachable) is
  retried with backoff; if it still fails, `handle` raises so the consumer does
  **not** commit and the batch is redelivered. The canonical producer is
  idempotent, so redelivery cannot duplicate a committed record on a partition.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from aiokafka.structs import ConsumerRecord
from pydantic import ValidationError

from sm_common.bus import EventBusProducer, dlq_payload
from sm_common.clock import utcnow
from sm_common.ids import uuid7
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
from .topics import CANONICAL_TOPIC, DLQ_TOPIC
from .version import PRODUCER

__all__ = ["NormalizationEngine"]

_log = structlog.get_logger("sm.normalization.engine")


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
        dlq_topic: str = DLQ_TOPIC,
        produce_attempts: int = 3,
    ) -> None:
        self._producer = producer
        self._group = consumer_group
        self._metrics = metrics
        self._m = norm_metrics
        self._enrichers = enrichers
        self._canonical_topic = canonical_topic
        self._dlq_topic = dlq_topic
        self._attempts = produce_attempts

    async def handle(self, record: ConsumerRecord) -> None:
        raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")

        try:
            doc: Any = json.loads(raw)
            event_type = EventType(doc["event_type"])
        except (ValueError, TypeError, KeyError) as exc:
            await self._dead_letter(record, raw, "unparseable", repr(exc))
            return

        payload_model = EVENT_PAYLOAD_REGISTRY.get(event_type)
        if payload_model is None:
            await self._dead_letter(record, raw, "unknown_event_type", event_type.value)
            return

        try:
            envelope = EventEnvelope[payload_model].model_validate(doc)  # type: ignore[valid-type]
        except ValidationError as exc:
            await self._dead_letter(record, raw, "envelope_invalid", str(exc))
            return

        self._m.consumed_inc(event_type.value)

        try:
            canonical = normalize(envelope)
        except UnknownEventTypeError as exc:
            await self._dead_letter(record, raw, "unknown_event_type", str(exc))
            return
        except Exception as exc:  # a mapper bug — do not wedge the partition
            _log.exception("normalize_failed", event_type=event_type.value)
            await self._dead_letter(record, raw, "normalize_failed", repr(exc))
            return

        enrichment = await run_enrichers(canonical, self._enrichers)
        if enrichment:
            canonical = canonical.model_copy(update={"enrichment": enrichment})

        out = self._wrap(envelope, canonical)
        await self._produce(
            self._canonical_topic, key=out.partition_key, value=out.model_dump_json().encode("utf-8")
        )
        self._m.produced_inc(event_type.value)

    # ----------------------------------------------------------------- #
    def _wrap(
        self, source: EventEnvelope[Any], canonical: CanonicalEventPayload
    ) -> EventEnvelope[CanonicalEventPayload]:
        primary = (canonical.actor or canonical.target or (canonical.entities[0] if canonical.entities else None))
        partition_key = make_partition_key(
            source.tenant_id, primary.value if primary else "unknown"
        )
        return EventEnvelope[CanonicalEventPayload](
            event_id=uuid7(),
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

    async def _produce(self, topic: str, *, key: str, value: bytes) -> None:
        last: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                await self._producer.send(topic, key=key, value=value)
                return
            except Exception as exc:  # transient broker error
                last = exc
                _log.warning("produce_retry", topic=topic, attempt=attempt, error_type=type(exc).__name__)
                await asyncio.sleep(min(2 ** (attempt - 1), 5))
        self._m.produce_error_inc(topic)
        raise RuntimeError(f"produce to {topic} failed after {self._attempts} attempts") from last

    async def _dead_letter(
        self, record: ConsumerRecord, raw: bytes, reason: str, detail: str
    ) -> None:
        payload = dlq_payload(
            original=raw, error_type=reason, error_detail=detail,
            consumer_group=self._group, attempts=1,
        )
        key = record.key.decode("utf-8", "replace") if record.key else "unknown"
        await self._produce(self._dlq_topic, key=key, value=payload)
        self._m.dlq_inc(reason)
        _log.warning("record_dead_lettered", reason=reason, partition=record.partition, offset=record.offset)
