"""Direct-SQL content reads from `detection-engine`'s own Postgres tables
(req 22; service-catalog "consumes detection-engine ... sync, for content").

`detection-engine` exposes no internal read HTTP API of its own — it only
emits to Kafka. `api-gateway`'s `SqlSocRepository` already established the
precedent for reading these tables directly, tenant-scoped, from another
service; this mirrors that. Every query is bounded and never writes.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from sm_common.db import Database
from sm_common.db import Detection as DetectionRow
from sm_common.db import ThreatScore as ThreatScoreRow
from sm_contracts import Detection, EvidenceItem, Severity, ThreatScore, ThreatSubjectType
from sm_contracts.telemetry import EntityRef

__all__ = ["ContentRepository"]

#: Bounded recency window app-filtered by entity below — matches
#: `SqlSocRepository.entity_timeline`'s scan size.
_SCAN_LIMIT = 200


def _entity_refs(raw: list[object]) -> list[EntityRef]:
    return [
        EntityRef(kind=str(e["kind"]), value=str(e["value"]))
        for e in raw
        if isinstance(e, dict) and "kind" in e and "value" in e
    ]


def _detection_out(r: DetectionRow) -> Detection:
    return Detection(
        id=r.id, tenant_id=r.tenant_id, created_at=r.created_at, updated_at=r.updated_at,
        detector=r.detector, rule_id=r.rule_id, title=r.title, description=r.description,
        severity=Severity(r.severity), score=r.score, scoring_status=r.scoring_status,
        status=r.status, entities=_entity_refs(list(r.entities)),
        technique_ids=list(r.technique_ids),
        evidence=[EvidenceItem.model_validate(e) for e in r.evidence],
        raw_event_id=r.raw_event_id, dedup_key=r.dedup_key,
        first_seen=r.first_seen, last_seen=r.last_seen,
    )


def _score_out(r: ThreatScoreRow) -> ThreatScore:
    return ThreatScore(
        id=r.id, tenant_id=r.tenant_id, created_at=r.created_at, updated_at=r.updated_at,
        subject_type=ThreatSubjectType(r.subject_type), subject_id=r.subject_id, score=r.score,
        components=dict(r.components), weights_version=r.weights_version,
        scoring_status=r.scoring_status, computed_at=r.computed_at,
    )


class ContentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_detection(self, tenant_id: UUID, detection_id: UUID) -> Detection | None:
        async with self._db.session() as s:
            row = await s.get(DetectionRow, detection_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return _detection_out(row)

    async def list_detections_for_subject(
        self, tenant_id: UUID, *, subject_type: str, subject_id: str, limit: int = 50,
    ) -> list[Detection]:
        """Every detection (within a bounded recency window) whose
        `entities` names this subject. `detection` carries no
        `subject_type`/`subject_id` column of its own — one detection can
        name several entities — so this is an app-level filter, the same
        approach `SqlSocRepository.entity_timeline` uses."""
        stmt = (
            select(DetectionRow)
            .where(DetectionRow.tenant_id == tenant_id)
            .order_by(DetectionRow.first_seen.desc())
            .limit(_SCAN_LIMIT)
        )
        async with self._db.session() as s:
            rows = (await s.execute(stmt)).scalars().all()
        matched = [
            r for r in rows
            if any(
                isinstance(e, dict) and e.get("kind") == subject_type and str(e.get("value")) == subject_id
                for e in r.entities
            )
        ]
        return [_detection_out(r) for r in matched[:limit]]

    async def get_threat_score(
        self, tenant_id: UUID, *, subject_type: str, subject_id: str,
    ) -> ThreatScore | None:
        stmt = select(ThreatScoreRow).where(
            ThreatScoreRow.tenant_id == tenant_id,
            ThreatScoreRow.subject_type == subject_type,
            ThreatScoreRow.subject_id == subject_id,
        )
        async with self._db.session() as s:
            row = (await s.execute(stmt)).scalar_one_or_none()
        return _score_out(row) if row is not None else None
