"""Domain handler: one `detections` record -> `technique_mapping` rows.

Wrapped by `sm_common.bus.RecordProcessor`:
- unparseable / not a `detection.raised` envelope -> `PoisonError` (DLQ).
- a database write failure -> `TransientError` (retry).

Catalog absent (no import run) -> every technique id is `unmapped`, a metric
fires, nothing is written. No technique is fabricated.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from aiokafka.structs import ConsumerRecord
from pydantic import ValidationError

from sm_common.bus import PoisonError, TransientError
from sm_contracts import (
    DetectionPayload,
    EventEnvelope,
    EventType,
    EvidenceItem,
    EvidenceKind,
    MappingSubjectType,
)

from .mapping import MappingEngine
from .metrics import MitreMetrics

__all__ = ["MappingHandler"]

_log = structlog.get_logger("sm.mitre_service.engine")


class MappingHandler:
    def __init__(self, *, engine: MappingEngine, metrics: MitreMetrics) -> None:
        self._engine = engine
        self._m = metrics

    async def handle(self, record: ConsumerRecord) -> None:
        envelope = _parse(record)
        payload = envelope.payload
        if not payload.technique_ids:
            self._m.detection(mapped=0, unmapped=0)
            return

        rationale = f"named by detection {payload.rule_id or payload.detector.value}"
        result = await self._engine.map_techniques(list(payload.technique_ids), rationale=rationale)

        try:
            written = await self._engine.persist(
                tenant_id=payload.tenant_id,
                subject_type=MappingSubjectType.detection,
                subject_id=payload.detection_id,
                result=result,
                evidence=[EvidenceItem(
                    kind=EvidenceKind.technique, ref=result.matrix_version or "no-catalog",
                    summary=f"mapped from detection {payload.detection_id}",
                    provenance=f"mitre-service:{payload.detection_id}",
                )],
            )
        except Exception as exc:
            raise TransientError(f"technique_mapping write failed: {exc!r}") from exc

        self._m.detection(mapped=written, unmapped=len(result.unmapped))
        if result.unmapped:
            _log.info("techniques_unmapped", ids=result.unmapped,
                      matrix_version=result.matrix_version, detection_id=str(payload.detection_id))


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
