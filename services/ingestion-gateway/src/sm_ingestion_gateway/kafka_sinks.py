"""Kafka-backed `RawEventSink` / `DeadLetterSink` (event-model.md).

These are the real implementations behind the interfaces in `sinks.py`; the
route and pipeline code is unchanged. Selected by `build_services` when
`SM_EVENT_BUS_ENABLED=true`.

- `KafkaRawEventSink` writes the accepted envelope (canonical JSON) to
  `telemetry.raw`, keyed on `partition_key`. A produce failure propagates — the
  pipeline turns it into `503` so the sensor retries. The producer is idempotent,
  so that retry cannot duplicate a record on a partition.
- `KafkaDeadLetterSink` writes the rejected raw body verbatim to
  `telemetry.raw.dlq` with the reason and source in headers, keyed on the sensor
  id so one sensor's bad traffic stays on one partition.

Topics are auto-created by Redpanda locally; a real deployment pre-creates them
with the partition counts in `event-model.md`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sm_common.bus import EventBusProducer
from sm_contracts import EventEnvelope, EventType, dlq_topic, topic_for_event_type

__all__ = ["DLQ_TOPIC", "RAW_TOPIC", "KafkaDeadLetterSink", "KafkaRawEventSink"]

RAW_TOPIC = topic_for_event_type(EventType.telemetry_network_flow)  # all telemetry.* -> telemetry.raw
DLQ_TOPIC = dlq_topic(RAW_TOPIC)


class KafkaRawEventSink:
    def __init__(self, producer: EventBusProducer, *, topic: str = RAW_TOPIC) -> None:
        self._producer = producer
        self._topic = topic

    async def put(self, envelope: EventEnvelope[Any]) -> None:
        await self._producer.send(
            self._topic,
            key=envelope.partition_key,
            value=envelope.model_dump_json().encode("utf-8"),
        )


class KafkaDeadLetterSink:
    def __init__(self, producer: EventBusProducer, *, topic: str = DLQ_TOPIC) -> None:
        self._producer = producer
        self._topic = topic

    async def put(
        self, *, source_type: str, raw_body: bytes, reason: str, sensor_id: UUID | None
    ) -> None:
        headers: list[tuple[str, bytes]] = [
            ("reason", reason.encode("utf-8")),
            ("source_type", source_type.encode("utf-8")),
        ]
        if sensor_id is not None:
            headers.append(("sensor_id", str(sensor_id).encode("utf-8")))
        await self._producer.send(
            self._topic,
            key=str(sensor_id) if sensor_id is not None else "unknown",
            value=raw_body,
            headers=headers,
        )
