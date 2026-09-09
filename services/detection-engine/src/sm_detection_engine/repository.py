"""Persistence for the detection domain (Postgres, `detection-engine`-owned).

Every write is tenant-scoped by the row's own `tenant_id`, which comes from the
canonical event — never a request field. Detections and threat scores upsert on a
deterministic key so an at-least-once reprocess updates rather than duplicates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from sm_common.db import Anomaly, Database, Detection, SecurityAlert, ThreatScore
from sm_common.ids import uuid7

__all__ = ["DetectionRepository"]


class DetectionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add_anomaly(
        self,
        *,
        tenant_id: UUID,
        method: str,
        feature_schema_version: str,
        model_version: str | None,
        score: float,
        normalized_score: float,
        threshold: float,
        is_anomaly: bool,
        entity: dict[str, Any] | None,
        raw_event_id: UUID | None,
        observed_at: datetime,
        features: dict[str, float],
    ) -> None:
        async with self._db.transaction() as s:
            s.add(Anomaly(
                id=uuid7(), tenant_id=tenant_id, method=method,
                feature_schema_version=feature_schema_version, model_version=model_version,
                score=score, normalized_score=normalized_score, threshold=threshold,
                is_anomaly=is_anomaly, entity=entity, raw_event_id=raw_event_id,
                observed_at=observed_at, features=features,
            ))

    async def upsert_detection(
        self,
        *,
        detection_id: UUID,
        tenant_id: UUID,
        detector: str,
        rule_id: str | None,
        title: str,
        description: str,
        severity: str,
        score: float,
        scoring_status: str,
        entities: list[dict[str, Any]],
        technique_ids: list[str],
        evidence: list[dict[str, Any]],
        raw_event_id: UUID | None,
        dedup_key: str,
        occurred_at: datetime,
    ) -> None:
        stmt = insert(Detection).values(
            id=detection_id, tenant_id=tenant_id, detector=detector, rule_id=rule_id,
            title=title, description=description, severity=severity, score=score,
            scoring_status=scoring_status, status="new", entities=entities,
            technique_ids=technique_ids, evidence=evidence, raw_event_id=raw_event_id,
            dedup_key=dedup_key, first_seen=occurred_at, last_seen=occurred_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Detection.id],
            set_={
                "title": stmt.excluded.title,
                "description": stmt.excluded.description,
                "severity": stmt.excluded.severity,
                "score": stmt.excluded.score,
                "scoring_status": stmt.excluded.scoring_status,
                "entities": stmt.excluded.entities,
                "technique_ids": stmt.excluded.technique_ids,
                "evidence": stmt.excluded.evidence,
                "raw_event_id": stmt.excluded.raw_event_id,
                "last_seen": stmt.excluded.last_seen,
            },
            where=Detection.status == "new",
        )
        async with self._db.transaction() as s:
            await s.execute(stmt)

    async def upsert_threat_score(
        self,
        *,
        tenant_id: UUID,
        subject_type: str,
        subject_id: str,
        score: float,
        components: dict[str, float],
        weights_version: str,
        scoring_status: str,
        computed_at: datetime,
    ) -> None:
        stmt = insert(ThreatScore).values(
            id=uuid7(), tenant_id=tenant_id, subject_type=subject_type, subject_id=subject_id,
            score=score, components=components, weights_version=weights_version,
            scoring_status=scoring_status, computed_at=computed_at,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_threat_score_subject",
            set_={
                "score": stmt.excluded.score,
                "components": stmt.excluded.components,
                "weights_version": stmt.excluded.weights_version,
                "scoring_status": stmt.excluded.scoring_status,
                "computed_at": stmt.excluded.computed_at,
            },
        )
        async with self._db.transaction() as s:
            await s.execute(stmt)

    async def ensure_alert(
        self,
        *,
        detection_id: UUID,
        tenant_id: UUID,
        severity: str,
        title: str,
        summary: str,
        opened_at: datetime,
    ) -> bool:
        stmt = (
            insert(SecurityAlert)
            .values(
                id=uuid7(), tenant_id=tenant_id, detection_id=detection_id, severity=severity,
                status="open", title=title, summary=summary, opened_at=opened_at,
            )
            .on_conflict_do_nothing(constraint="uq_security_alert_detection_id")
            .returning(SecurityAlert.id)
        )
        async with self._db.transaction() as s:
            row = (await s.execute(stmt)).first()
        return row is not None
