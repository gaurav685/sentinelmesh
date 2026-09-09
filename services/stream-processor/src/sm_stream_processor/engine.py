"""Domain handler: `events.canonical` record -> `graph.commands`.

Wrapped by `sm_common.bus.RecordProcessor` (retry / DLQ policy). This handler
signals intent only:

- unparseable / not an `event.canonical` envelope -> `PoisonError`.
- a failed produce to `graph.commands` -> `TransientError`.

Idempotent: every emitted command's id is deterministic in the source canonical
`event_id`, so a redelivery re-emits identical ids and `graph-writer` dedups.
Commands from one source event are produced in order (nodes then the edge); a
partial failure retries the whole handler, re-emitting the already-sent commands
(harmless — same ids).
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from aiokafka.structs import ConsumerRecord
from pydantic import ValidationError

from sm_common.bus import EventBusProducer, PoisonError, TransientError
from sm_common.observability import Metrics
from sm_contracts import CanonicalEventPayload, EventEnvelope, EventType

from .emitter import emit
from .metrics import StreamMetrics
from .topics import GRAPH_COMMANDS_TOPIC

__all__ = ["StreamEngine"]

_log = structlog.get_logger("sm.stream_processor.engine")


class StreamEngine:
    def __init__(
        self,
        *,
        producer: EventBusProducer,
        metrics: Metrics,
        stream_metrics: StreamMetrics,
        commands_topic: str = GRAPH_COMMANDS_TOPIC,
    ) -> None:
        self._producer = producer
        self._metrics = metrics
        self._m = stream_metrics
        self._commands_topic = commands_topic

    async def handle(self, record: ConsumerRecord) -> None:
        raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")
        try:
            doc: Any = json.loads(raw)
            if doc.get("event_type") != EventType.event_canonical.value:
                raise PoisonError(f"not an event.canonical record: {doc.get('event_type')!r}")
            envelope = EventEnvelope[CanonicalEventPayload].model_validate(doc)
        except (ValueError, TypeError, KeyError) as exc:
            raise PoisonError(f"unparseable events.canonical record: {exc!r}") from exc
        except ValidationError as exc:
            raise PoisonError(f"canonical envelope invalid: {exc}") from exc

        self._m.consumed_inc(envelope.payload.kind.value)

        commands = emit(envelope)
        for cmd in commands:
            try:
                await self._producer.send(
                    self._commands_topic,
                    key=cmd.partition_key,
                    value=cmd.model_dump_json().encode("utf-8"),
                )
            except Exception as exc:
                raise TransientError(
                    f"produce to {self._commands_topic} failed: {exc!r}"
                ) from exc
            self._m.command_inc(cmd.payload.op.value)

        _log.debug(
            "canonical_processed", kind=envelope.payload.kind.value,
            commands=len(commands), raw_event_id=str(envelope.payload.raw_event_id),
        )
