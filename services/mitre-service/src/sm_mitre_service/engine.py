"""Domain handler: a `detections` or `attack_chains` record -> `technique_mapping` rows.

Wrapped by `sm_common.bus.RecordProcessor`:
- unparseable / an unexpected event type -> `PoisonError` (DLQ).
- a database write failure -> `TransientError` (retry).

Both a detection and an attack chain carry the candidate ATT&CK technique ids
their upstream already named. Mapping is *validation + enrichment* against the
imported catalog: an unknown id is `unmapped`, a metric fires, nothing is
written. No technique is fabricated. Catalog absent -> everything `unmapped`.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
from aiokafka.structs import ConsumerRecord
from pydantic import ValidationError

from sm_common.bus import PoisonError, TransientError
from sm_contracts import (
    AttackChainPayload,
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

_HANDLED = {EventType.detection_raised.value, EventType.attack_chain_updated.value}


class MappingHandler:
    def __init__(self, *, engine: MappingEngine, metrics: MitreMetrics) -> None:
        self._engine = engine
        self._m = metrics

    async def handle(self, record: ConsumerRecord) -> None:
        subject_type, subject_id, tenant_id, technique_ids, rationale = _parse(record)

        if not technique_ids:
            self._m.detection(mapped=0, unmapped=0)
            return

        result = await self._engine.map_techniques(list(technique_ids), rationale=rationale)
        try:
            written = await self._engine.persist(
                tenant_id=tenant_id, subject_type=subject_type, subject_id=subject_id, result=result,
                evidence=[EvidenceItem(
                    kind=EvidenceKind.technique, ref=result.matrix_version or "no-catalog",
                    summary=f"mapped from {subject_type.value} {subject_id}",
                    provenance=f"mitre-service:{subject_id}",
                )],
            )
        except Exception as exc:
            raise TransientError(f"technique_mapping write failed: {exc!r}") from exc

        self._m.detection(mapped=written, unmapped=len(result.unmapped))
        if result.unmapped:
            _log.info("techniques_unmapped", ids=result.unmapped,
                      matrix_version=result.matrix_version,
                      subject_type=subject_type.value, subject_id=str(subject_id))


def _parse(
    record: ConsumerRecord,
) -> tuple[MappingSubjectType, UUID, UUID, tuple[str, ...], str]:
    raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")
    try:
        doc: Any = json.loads(raw)
        etype = doc.get("event_type")
        if etype not in _HANDLED:
            raise PoisonError(f"unexpected event type for mitre mapping: {etype!r}")
        if etype == EventType.detection_raised.value:
            env_d = EventEnvelope[DetectionPayload].model_validate(doc)
            p = env_d.payload
            return (
                MappingSubjectType.detection, p.detection_id, p.tenant_id,
                tuple(p.technique_ids),
                f"named by detection {p.rule_id or p.detector.value}",
            )
        env_c = EventEnvelope[AttackChainPayload].model_validate(doc)
        c = env_c.payload
        return (
            MappingSubjectType.attack_chain, c.chain_id, c.tenant_id, tuple(c.technique_ids),
            f"aggregated across the {c.detection_count} detection(s) in attack chain {c.chain_id}",
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PoisonError(f"unparseable mapping record: {exc!r}") from exc
    except ValidationError as exc:
        raise PoisonError(f"mapping envelope invalid: {exc}") from exc
