"""The ingest pipeline, independent of HTTP.

`ingest_one` is the whole path for a single event: dedup → parse → validate +
build envelope → sink. It raises the canonical `SmError`s (`NotFound`,
`ValidationFailed`) so the FastAPI handler renders the right status; a rejected
event is written to the DLQ *before* the error is raised so nothing is dropped.

`ingest_batch` runs the same steps per element but never raises for a single bad
element — it collects per-index outcomes so one broken event does not fail the
rest of the batch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any
from uuid import UUID

import structlog
from pydantic import ValidationError

from sm_common.errors import DependencyUnavailable, ValidationFailed
from sm_common.security import SensorIdentity
from sm_contracts import ErrorDetail, EventEnvelope

from .dedup import Dedup, DedupState
from .envelope import build_envelope
from .metrics import IngestionMetrics
from .sinks import DeadLetterSink, RawEventSink
from .source_types import resolve_source_type

__all__ = [
    "BatchResult",
    "IngestContext",
    "IngestOutcome",
    "OneResult",
    "ingest_batch",
    "ingest_one",
]

_MAX_DETAILS = 20

_log = structlog.get_logger("sm.ingestion.pipeline")


@dataclass
class IngestContext:
    raw_sink: RawEventSink
    dlq_sink: DeadLetterSink
    dedup: Dedup
    metrics: IngestionMetrics


async def _sink_accepted(ctx: IngestContext, envelope: EventEnvelope[Any], source_type: str) -> None:
    """Produce an accepted event. A sink failure is a `503`: the event is valid
    and must not be lost, so the sensor has to retry."""
    try:
        await ctx.raw_sink.put(envelope)
    except Exception as exc:
        ctx.metrics.sink_error_inc("raw")
        _log.error("raw_sink_failed", error_type=type(exc).__name__, event_id=str(envelope.event_id))
        raise DependencyUnavailable("the event bus is unavailable; retry") from exc
    ctx.metrics.accepted_inc(source_type)


async def _dead_letter(
    ctx: IngestContext, *, source_type: str, raw_body: bytes, reason: str, sensor_id: UUID | None
) -> None:
    """Best-effort DLQ write. Never raises — the caller is already returning a
    4xx and must not have it turned into a 5xx by a second sink failure."""
    try:
        await ctx.dlq_sink.put(
            source_type=source_type, raw_body=raw_body, reason=reason, sensor_id=sensor_id
        )
    except Exception as exc:
        ctx.metrics.sink_error_inc("dlq")
        _log.error("dlq_sink_failed", error_type=type(exc).__name__, reason=reason)


class IngestOutcome(Enum):
    accepted = auto()
    duplicate = auto()


@dataclass(frozen=True)
class OneResult:
    outcome: IngestOutcome
    event_id: UUID | None


def _details(err: ValidationError) -> list[ErrorDetail]:
    out: list[ErrorDetail] = []
    for e in err.errors()[:_MAX_DETAILS]:
        loc = ".".join(str(p) for p in e.get("loc", ()))
        out.append(ErrorDetail(field=loc or "payload", issue=e.get("type", "invalid")))
    return out


async def ingest_one(
    ctx: IngestContext,
    *,
    identity: SensorIdentity,
    source_type: str,
    raw_body: bytes,
    client_event_id: str | None,
) -> OneResult:
    event_type, payload_model = resolve_source_type(source_type)  # NotFound -> 404

    if client_event_id:
        state = await ctx.dedup.check_and_mark(identity.sensor_id, client_event_id)
        if state is DedupState.duplicate:
            ctx.metrics.duplicate_inc(source_type)
            return OneResult(IngestOutcome.duplicate, None)
        if state is DedupState.unavailable:
            ctx.metrics.dedup_error_inc()

    async def _reject(reason: str) -> None:
        await _dead_letter(
            ctx, source_type=source_type, raw_body=raw_body, reason=reason,
            sensor_id=identity.sensor_id,
        )
        ctx.metrics.rejected_inc(source_type)
        # The event was never accepted; free the id so a corrected retry with the
        # same X-Sensor-Event-Id is not suppressed as a duplicate.
        if client_event_id:
            await ctx.dedup.forget(identity.sensor_id, client_event_id)

    try:
        parsed = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        await _reject("invalid_json")
        raise ValidationFailed("request body is not valid JSON") from None

    try:
        envelope = build_envelope(
            event_type=event_type, payload_model=payload_model, raw_payload=parsed,
            identity=identity, client_event_id=client_event_id,
        )
    except ValidationError as exc:
        await _reject("schema_validation")
        raise ValidationFailed("telemetry payload failed validation", details=_details(exc)) from None

    await _sink_accepted(ctx, envelope, source_type)
    return OneResult(IngestOutcome.accepted, envelope.event_id)


@dataclass(frozen=True)
class BatchResult:
    event_ids: list[UUID]
    rejected: list[tuple[int, str]]


async def ingest_batch(
    ctx: IngestContext,
    *,
    identity: SensorIdentity,
    source_type: str,
    events: list[dict[str, Any]],
) -> BatchResult:
    event_type, payload_model = resolve_source_type(source_type)  # NotFound -> 404

    event_ids: list[UUID] = []
    rejected: list[tuple[int, str]] = []
    for index, body in enumerate(events):
        try:
            envelope = build_envelope(
                event_type=event_type, payload_model=payload_model, raw_payload=body,
                identity=identity, client_event_id=None,
            )
        except ValidationError:
            raw = json.dumps(body).encode()
            await _dead_letter(
                ctx, source_type=source_type, raw_body=raw, reason="schema_validation",
                sensor_id=identity.sensor_id,
            )
            ctx.metrics.rejected_inc(source_type)
            rejected.append((index, "schema_validation"))
            continue
        # A produce failure aborts the batch with 503; the sensor retries the
        # whole batch (downstream consumers are idempotent on event_id).
        await _sink_accepted(ctx, envelope, source_type)
        event_ids.append(envelope.event_id)

    return BatchResult(event_ids=event_ids, rejected=rejected)
