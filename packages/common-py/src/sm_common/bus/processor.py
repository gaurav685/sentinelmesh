"""Shared retry + dead-letter policy for a stream consumer (event-model.md §4/§5).

`RecordProcessor` wraps a domain handler into a `RecordHandler` for
`EventBusConsumer.run`. The domain handler signals intent by exception:

- raise `PoisonError` — the record can never succeed (bad JSON, failed schema,
  a bug in the mapper). Written to `<source topic>.dlq` immediately; the
  processor returns so the consumer commits and the partition keeps moving.
- raise `TransientError` — a downstream dependency is momentarily unavailable.
  Retried in-process with exponential backoff up to `max_attempts`, then
  dead-lettered.
- raise **anything else** — treated as an infrastructure failure of the
  processor itself: it propagates, the consumer does **not** commit, and the
  batch is redelivered (`EventBusConsumer` rewinds the fetch position).

The DLQ record is `dlq_payload(...)` — the original bytes plus why it failed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog
from aiokafka.structs import ConsumerRecord
from opentelemetry.trace import SpanKind

from ..observability import Metrics, get_tracer, remote_context_from_trace_id
from .consumer import dlq_payload
from .producer import EventBusProducer

__all__ = ["PoisonError", "RecordProcessor", "TransientError"]

_log = structlog.get_logger("sm.bus.processor")
_tracer = get_tracer("sm.bus.consumer")

DomainHandler = Callable[[ConsumerRecord], Awaitable[None]]


def _peek_trace_id(record: ConsumerRecord) -> str | None:
    """Best-effort read of the envelope's `trace_id` for span linking. Never
    raises — a malformed record is the domain handler's problem (it will
    raise `PoisonError`), not tracing's; this just falls back to no link."""
    try:
        raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")
        doc = json.loads(raw)
        trace_id = doc.get("trace_id")
        return trace_id if isinstance(trace_id, str) else None
    except Exception:
        return None


class PoisonError(Exception):
    """The record cannot ever be processed — dead-letter it now."""


class TransientError(Exception):
    """A momentary downstream failure — retry, then dead-letter."""


def _default_dlq(topic: str) -> str:
    return f"{topic}.dlq"


@dataclass
class RecordProcessor:
    producer: EventBusProducer
    consumer_group: str
    handle: DomainHandler
    metrics: Metrics | None = None
    service_name: str = ""
    max_attempts: int = 3
    dlq_topic_for: Callable[[str], str] = field(default=_default_dlq)
    backoff_cap_s: float = 5.0

    async def __call__(self, record: ConsumerRecord) -> None:
        raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")
        parent_ctx = remote_context_from_trace_id(_peek_trace_id(record))
        attempt = 0
        while True:
            attempt += 1
            try:
                with _tracer.start_as_current_span(
                    f"consume {record.topic}", context=parent_ctx, kind=SpanKind.CONSUMER
                ) as span:
                    span.set_attribute("messaging.system", "kafka")
                    span.set_attribute("messaging.destination", record.topic)
                    span.set_attribute("messaging.kafka.consumer_group", self.consumer_group)
                    await self.handle(record)
                return
            except PoisonError as exc:
                await self._dead_letter(record, raw, "poison", repr(exc), attempt)
                return
            except TransientError as exc:
                if attempt >= self.max_attempts:
                    await self._dead_letter(record, raw, "retries_exhausted", repr(exc), attempt)
                    return
                if self.metrics is not None:
                    self.metrics.consumer_retries.labels(self.service_name, self.consumer_group).inc()
                _log.warning(
                    "handler_retry", group=self.consumer_group, attempt=attempt,
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(min(2 ** (attempt - 1), self.backoff_cap_s))

    async def _dead_letter(
        self, record: ConsumerRecord, raw: bytes, category: str, detail: str, attempts: int
    ) -> None:
        target = self.dlq_topic_for(record.topic)
        payload = dlq_payload(
            original=raw, error_type=category, error_detail=detail,
            consumer_group=self.consumer_group, attempts=attempts,
        )
        key = record.key.decode("utf-8", "replace") if record.key else "unknown"
        await self.producer.send(target, key=key, value=payload)
        if self.metrics is not None:
            self.metrics.consumer_dlq.labels(self.service_name, self.consumer_group, category).inc()
        _log.warning(
            "record_dead_lettered", group=self.consumer_group, dlq=target,
            category=category, partition=record.partition, offset=record.offset,
        )
