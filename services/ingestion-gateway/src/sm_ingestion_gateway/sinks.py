"""Where an event goes after the gateway is done with it.

Two boundaries, both interfaces here:

- `RawEventSink` — an accepted, validated `EventEnvelope`. In Phase 3 this is a
  Kafka producer writing the `telemetry.raw` topic. Until then the stopgap
  (`LoggingRawEventSink`) logs one structured line per event and counts them, so
  the rest of the pipeline can be built and tested against the interface.
- `DeadLetterSink` — a body the gateway rejected (bad JSON, failed schema). In
  Phase 3 this is the `telemetry.raw.dlq` topic. The stopgap
  (`LoggingDeadLetterSink`) logs the reason and the raw bytes (capped) so a
  malformed sensor can be diagnosed without the payload being silently dropped.

Neither stopgap is durable. `docs/IMPLEMENTATION_STATE.md` records this as the
known gap that Unit 3 closes.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

import structlog

from sm_contracts import EventEnvelope

__all__ = [
    "DeadLetterSink",
    "LoggingDeadLetterSink",
    "LoggingRawEventSink",
    "RawEventSink",
]

_log = structlog.get_logger("sm.ingestion.sink")

_DLQ_BODY_CAP = 4096


class RawEventSink(Protocol):
    async def put(self, envelope: EventEnvelope[Any]) -> None: ...


class DeadLetterSink(Protocol):
    async def put(
        self,
        *,
        source_type: str,
        raw_body: bytes,
        reason: str,
        sensor_id: UUID | None,
    ) -> None: ...


class LoggingRawEventSink:
    """Stopgap `RawEventSink`: structured log line + a process counter."""

    def __init__(self) -> None:
        self.count = 0

    async def put(self, envelope: EventEnvelope[Any]) -> None:
        self.count += 1
        _log.info(
            "raw_event_accepted",
            event_id=str(envelope.event_id),
            event_type=envelope.event_type.value,
            tenant_id=str(envelope.tenant_id),
            partition_key=envelope.partition_key,
        )


class LoggingDeadLetterSink:
    """Stopgap `DeadLetterSink`: structured warning + a process counter."""

    def __init__(self) -> None:
        self.count = 0

    async def put(
        self,
        *,
        source_type: str,
        raw_body: bytes,
        reason: str,
        sensor_id: UUID | None,
    ) -> None:
        self.count += 1
        _log.warning(
            "raw_event_dead_lettered",
            source_type=source_type,
            reason=reason,
            sensor_id=str(sensor_id) if sensor_id else None,
            body_bytes=len(raw_body),
            body_preview=raw_body[:_DLQ_BODY_CAP].decode("utf-8", "replace"),
        )
