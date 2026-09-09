"""Domain handler: one `detections` record -> an updated attack chain.

    detection -> stage -> chain (upsert) -> attack_chains event

Wrapped by `sm_common.bus.RecordProcessor`:
- unparseable / not a `detection.raised` envelope -> `PoisonError` (DLQ).
- a database write failure or a failed produce to `attack_chains` -> `TransientError`.

A chain is a correlation of detections, never a verdict: its `confidence` is
probabilistic (capped below 1.0) and its status is never auto-`confirmed`.
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
from sm_common.ids import new_correlation_id, uuid7
from sm_contracts import (
    AttackChainModel,
    AttackChainPayload,
    DetectionPayload,
    EventEnvelope,
    EventType,
    make_partition_key,
)

from .chains import ChainRepository
from .graph import chain_graph_commands
from .metrics import CorrelationMetrics
from .staging import resolve_subject, stage_detection
from .topics import CHAINS_TOPIC, GRAPH_COMMANDS_TOPIC
from .version import PRODUCER

__all__ = ["CorrelationHandler"]

_log = structlog.get_logger("sm.correlation_engine.engine")


class CorrelationHandler:
    def __init__(
        self, *, repo: ChainRepository, producer: EventBusProducer, metrics: CorrelationMetrics
    ) -> None:
        self._repo = repo
        self._producer = producer
        self._m = metrics

    async def handle(self, record: ConsumerRecord) -> None:
        envelope = _parse(record)
        payload = envelope.payload
        subject_type, subject_id = resolve_subject(payload)
        staged = stage_detection(payload)
        self._m.detection(staged.stage.value)

        try:
            update = await self._repo.correlate(
                staged, tenant_id=payload.tenant_id, subject_type=subject_type,
                subject_id=subject_id, now=utcnow(),
            )
        except Exception as exc:
            raise TransientError(f"chain correlate failed: {exc!r}") from exc

        self._m.chain(
            created=update.created, new_detection=update.new_detection,
            status=update.chain.status.value, stage=staged.stage.value,
        )

        if not update.new_detection and not update.created:
            # A pure redelivery changed nothing — still emit the current state so a
            # late consumer converges, but do not spam a fresh event id per retry.
            _log.debug("chain_unchanged", chain_id=str(update.chain.id))

        await self._emit(envelope, update.payload)
        await self._project_to_graph(envelope, update.chain)

    async def _project_to_graph(
        self, source: EventEnvelope[DetectionPayload], chain: AttackChainModel
    ) -> None:
        for env in chain_graph_commands(source, chain):
            try:
                await self._producer.send(
                    GRAPH_COMMANDS_TOPIC, key=env.partition_key,
                    value=env.model_dump_json().encode("utf-8"),
                )
            except Exception as exc:
                raise TransientError(f"produce to {GRAPH_COMMANDS_TOPIC} failed: {exc!r}") from exc
            self._m.graph_command(env.payload.op.value)

    async def _emit(
        self, source: EventEnvelope[DetectionPayload], payload: AttackChainPayload
    ) -> None:
        env = EventEnvelope[AttackChainPayload](
            event_id=uuid7(), event_type=EventType.attack_chain_updated, event_version=1,
            occurred_at=source.occurred_at, ingested_at=utcnow(), producer=PRODUCER,
            tenant_id=source.tenant_id, source=source.source,
            correlation_id=get_correlation_id() or source.correlation_id or new_correlation_id(),
            trace_id=source.trace_id,
            partition_key=make_partition_key(source.tenant_id, payload.subject_id),
            payload=payload, metadata={"detection_id": str(source.payload.detection_id)},
        )
        try:
            await self._producer.send(
                CHAINS_TOPIC, key=env.partition_key, value=env.model_dump_json().encode("utf-8")
            )
        except Exception as exc:
            raise TransientError(f"produce to {CHAINS_TOPIC} failed: {exc!r}") from exc


def _parse(record: ConsumerRecord) -> EventEnvelope[DetectionPayload]:
    raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")
    try:
        doc: Any = json.loads(raw)
        if doc.get("event_type") != EventType.detection_raised.value:
            raise PoisonError(f"not a detection.raised record: {doc.get('event_type')!r}")
        return EventEnvelope[DetectionPayload].model_validate(doc)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PoisonError(f"unparseable detections record: {exc!r}") from exc
    except ValidationError as exc:
        raise PoisonError(f"detection envelope invalid: {exc}") from exc
