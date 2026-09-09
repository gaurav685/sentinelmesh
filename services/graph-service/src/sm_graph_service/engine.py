"""Domain handler: one `graph.commands` record -> a Neo4j mutation + a `graph.events` record.

Wrapped by `sm_common.bus.RecordProcessor`. This handler signals intent only:

- unparseable record / not a `graph.command` envelope / a label off the
  allowlist / an unsupported op  -> `PoisonError` (straight to the DLQ).
- Neo4j unreachable                                       -> `TransientError` (retry).
- a failed produce to `graph.events`                      -> `TransientError` (retry).

Idempotent: the writer dedups on `command_id`, so an at-least-once redelivery is
a `DUPLICATE` no-op. The `graph.events` record's `event_id` is the `command_id`,
so the downstream projection dedups too.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from aiokafka.structs import ConsumerRecord
from pydantic import ValidationError

from sm_common.bus import EventBusProducer, PoisonError, TransientError
from sm_common.clock import utcnow
from sm_common.context import get_correlation_id
from sm_common.graph import GraphUnavailableError
from sm_common.ids import new_correlation_id
from sm_common.observability import Metrics
from sm_contracts import (
    EventEnvelope,
    EventType,
    GraphCommandPayload,
    GraphEventPayload,
    make_partition_key,
)

from .metrics import GraphMetrics
from .topics import EVENTS_TOPIC
from .version import PRODUCER
from .writer import GraphWriter, MutationResult

__all__ = ["GraphEngine"]

_log = structlog.get_logger("sm.graph_service.engine")


class GraphEngine:
    def __init__(
        self,
        *,
        writer: GraphWriter,
        producer: EventBusProducer,
        metrics: Metrics,
        graph_metrics: GraphMetrics,
        events_topic: str = EVENTS_TOPIC,
    ) -> None:
        self._writer = writer
        self._producer = producer
        self._metrics = metrics
        self._m = graph_metrics
        self._events_topic = events_topic

    async def handle(self, record: ConsumerRecord) -> None:
        envelope = _parse(record)
        cmd = envelope.payload

        try:
            result = await self._writer.apply(cmd)
        except GraphUnavailableError as exc:
            raise TransientError(f"neo4j unavailable: {exc}") from exc

        self._m.applied_inc(cmd.op.value, result.outcome.value)

        event = _event_envelope(envelope, cmd, result)
        try:
            await self._producer.send(
                self._events_topic,
                key=event.partition_key,
                value=event.model_dump_json().encode("utf-8"),
            )
        except Exception as exc:
            raise TransientError(f"produce to {self._events_topic} failed: {exc!r}") from exc

        _log.debug(
            "command_applied",
            op=cmd.op.value,
            outcome=result.outcome.value,
            label=cmd.label,
            command_id=str(cmd.command_id),
        )


def _parse(record: ConsumerRecord) -> EventEnvelope[GraphCommandPayload]:
    raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")
    try:
        doc: Any = json.loads(raw)
        if doc.get("event_type") != EventType.graph_command.value:
            raise PoisonError(f"not a graph.command record: {doc.get('event_type')!r}")
        return EventEnvelope[GraphCommandPayload].model_validate(doc)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PoisonError(f"unparseable graph.commands record: {exc!r}") from exc
    except ValidationError as exc:
        raise PoisonError(f"graph.command envelope invalid: {exc}") from exc


def _event_envelope(
    source: EventEnvelope[GraphCommandPayload],
    cmd: GraphCommandPayload,
    result: MutationResult,
) -> EventEnvelope[GraphEventPayload]:
    payload = GraphEventPayload(
        command_id=cmd.command_id,
        op=cmd.op,
        outcome=result.outcome,
        tenant_id=cmd.tenant_id,
        observed_at=cmd.observed_at,
        raw_event_id=cmd.raw_event_id,
        label=cmd.label,
        nodes_written=result.nodes_written,
        relationships_written=result.relationships_written,
    )
    return EventEnvelope[GraphEventPayload](
        event_id=cmd.command_id,
        event_type=EventType.graph_event,
        event_version=1,
        occurred_at=source.occurred_at,
        ingested_at=utcnow(),
        producer=PRODUCER,
        tenant_id=source.tenant_id,
        source=source.source,
        correlation_id=get_correlation_id() or source.correlation_id or new_correlation_id(),
        trace_id=source.trace_id,
        partition_key=make_partition_key(source.tenant_id, str(cmd.raw_event_id)),
        payload=payload,
        metadata={"raw_event_id": str(cmd.raw_event_id)},
    )
