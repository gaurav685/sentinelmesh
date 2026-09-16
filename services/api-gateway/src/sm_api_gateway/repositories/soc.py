"""Tenant-scoped SOC reads (Phase 9).

`api-gateway` is the browser-facing BFF. The detection / alert / threat-score
tables have no internal read API — `detection-engine` only emits to Kafka — so
the gateway reads them here, always with `WHERE tenant_id = :tenant` from the
authenticated `Principal` (Constitution §6). Attack chains, the graph, threat
intel and the MITRE heatmap are read by proxying their owning service with a
minted service token (`clients.py`).

Every statement is a parameterized SQLAlchemy construct. Lists are keyset-paged
on `created_at` (newest first), never offset — an unbounded scan is not possible.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_common.clock import utcnow
from sm_common.db import Detection as DetectionRow
from sm_common.db import HuntQueryRow
from sm_common.db import SecurityAlert as AlertRow
from sm_common.db import ThreatScore as ThreatScoreRow
from sm_common.db.intel_models import AttackTechniqueRow, TechniqueMappingRow
from sm_contracts import (
    Detection,
    MitreHeatmapCell,
    RiskSubject,
    SecurityAlert,
    Severity,
    SocSummary,
    ThreatScore,
    ThreatSubjectType,
    TimelineEntry,
)
from sm_contracts.telemetry import EntityRef

__all__ = ["SqlSocRepository"]

_MAX_LIMIT = 200


def _entity_refs(raw: list[object]) -> list[EntityRef]:
    out: list[EntityRef] = []
    for e in raw:
        if isinstance(e, dict) and "kind" in e and "value" in e:
            out.append(EntityRef(kind=str(e["kind"]), value=str(e["value"])))
    return out


class SqlSocRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ---- detections --------------------------------------------------
    async def list_detections(
        self, tenant_id: UUID, *, limit: int, before: datetime | None = None,
        severity: str | None = None, status: str | None = None,
    ) -> list[Detection]:
        stmt = (
            select(DetectionRow)
            .where(DetectionRow.tenant_id == tenant_id)
            .order_by(DetectionRow.created_at.desc(), DetectionRow.id.desc())
            .limit(min(limit, _MAX_LIMIT))
        )
        if before is not None:
            stmt = stmt.where(DetectionRow.created_at < before)
        if severity:
            stmt = stmt.where(DetectionRow.severity == severity)
        if status:
            stmt = stmt.where(DetectionRow.status == status)
        rows = (await self._s.execute(stmt)).scalars().all()
        return [self._detection(r) for r in rows]

    async def get_detection(self, tenant_id: UUID, detection_id: UUID) -> Detection | None:
        row = await self._s.get(DetectionRow, detection_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return self._detection(row)

    # ---- alerts ------------------------------------------------------
    async def list_alerts(
        self, tenant_id: UUID, *, limit: int, before: datetime | None = None,
        status: str | None = None,
    ) -> list[SecurityAlert]:
        stmt = (
            select(AlertRow)
            .where(AlertRow.tenant_id == tenant_id)
            .order_by(AlertRow.opened_at.desc(), AlertRow.id.desc())
            .limit(min(limit, _MAX_LIMIT))
        )
        if before is not None:
            stmt = stmt.where(AlertRow.created_at < before)
        if status:
            stmt = stmt.where(AlertRow.status == status)
        rows = (await self._s.execute(stmt)).scalars().all()
        return [self._alert(r) for r in rows]

    async def get_alert(self, tenant_id: UUID, alert_id: UUID) -> SecurityAlert | None:
        row = await self._s.get(AlertRow, alert_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return self._alert(row)

    # ---- threat scores --------------------------------------------
    async def top_risk(self, tenant_id: UUID, *, limit: int = 10) -> list[ThreatScore]:
        stmt = (
            select(ThreatScoreRow)
            .where(ThreatScoreRow.tenant_id == tenant_id)
            .order_by(ThreatScoreRow.score.desc())
            .limit(min(limit, _MAX_LIMIT))
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [self._score(r) for r in rows]

    # ---- dashboard summary ---------------------------------------
    async def summary(self, tenant_id: UUID) -> SocSummary:
        since = utcnow() - timedelta(hours=24)

        open_alerts = await self._s.scalar(
            select(func.count()).select_from(AlertRow)
            .where(AlertRow.tenant_id == tenant_id, AlertRow.status == "open")
        ) or 0
        sev_rows = (await self._s.execute(
            select(AlertRow.severity, func.count())
            .where(AlertRow.tenant_id == tenant_id, AlertRow.status == "open")
            .group_by(AlertRow.severity)
        )).all()
        detections_24h = await self._s.scalar(
            select(func.count()).select_from(DetectionRow)
            .where(DetectionRow.tenant_id == tenant_id, DetectionRow.created_at >= since)
        ) or 0
        active_chains = await self._s.scalar(
            select(func.count(func.distinct(ThreatScoreRow.subject_id)))
            .where(ThreatScoreRow.tenant_id == tenant_id, ThreatScoreRow.score >= 0.5)
        ) or 0

        top = await self.top_risk(tenant_id, limit=10)
        return SocSummary(
            generated_at=utcnow(),
            open_alerts=int(open_alerts),
            alerts_by_severity={str(s): int(c) for s, c in sev_rows},
            active_chains=int(active_chains),
            detections_24h=int(detections_24h),
            top_risk_subjects=[
                RiskSubject(
                    subject_type=t.subject_type, subject_id=t.subject_id, score=t.score,
                    scoring_status=t.scoring_status, computed_at=t.computed_at,
                )
                for t in top
            ],
        )

    # ---- MITRE heatmap (from technique_mapping, joined to the catalog for
    # the display name -- the catalog is in this same Postgres schema, not a
    # cross-service call, so this is a plain join rather than a second
    # round-trip to mitre-service) ---------------------------------
    async def mitre_heatmap(self, tenant_id: UUID) -> list[MitreHeatmapCell]:
        distinct = func.count(func.distinct(TechniqueMappingRow.subject_id)).label("n")
        stmt = (
            select(
                TechniqueMappingRow.technique_id,
                TechniqueMappingRow.tactic_id,
                AttackTechniqueRow.name,
                distinct,
            )
            .outerjoin(
                AttackTechniqueRow,
                AttackTechniqueRow.technique_id == TechniqueMappingRow.technique_id,
            )
            .where(TechniqueMappingRow.tenant_id == tenant_id)
            .group_by(TechniqueMappingRow.technique_id, TechniqueMappingRow.tactic_id, AttackTechniqueRow.name)
            .order_by(distinct.desc())
        )
        rows = (await self._s.execute(stmt)).all()
        return [
            MitreHeatmapCell(technique_id=tid, tactic_id=tac, name=name or "", subject_count=int(n))
            for tid, tac, name, n in rows
        ]

    # ---- entity timeline (detections + alerts for one subject) --
    async def entity_timeline(
        self, tenant_id: UUID, subject_id: str, *, limit: int = 200
    ) -> list[TimelineEntry]:
        det_stmt = (
            select(DetectionRow)
            .where(DetectionRow.tenant_id == tenant_id)
            .order_by(DetectionRow.first_seen.desc())
            .limit(_MAX_LIMIT)
        )
        entries: list[TimelineEntry] = []
        for r in (await self._s.execute(det_stmt)).scalars().all():
            values = {str(e.get("value")) for e in r.entities if isinstance(e, dict)}
            if subject_id not in values:
                continue
            entries.append(TimelineEntry(
                at=r.first_seen, kind="detection", severity=Severity(r.severity), title=r.title,
                ref_id=str(r.id), detail={"detector": r.detector, "status": r.status},
            ))
        entries.sort(key=lambda e: e.at, reverse=True)
        return entries[:limit]

    # ---- hunt history (Phase 11) --------------------------------
    async def record_hunt(
        self,
        tenant_id: UUID,
        *,
        principal: str,
        mode: str,
        nl_query: str | None,
        intent: str | None,
        supported: bool,
        row_count: int,
        cypher_fingerprint: str | None,
    ) -> UUID:
        row = HuntQueryRow(
            tenant_id=tenant_id,
            principal=principal[:256],
            mode=mode,
            nl_query=nl_query,
            intent=intent,
            supported=supported,
            row_count=row_count,
            cypher_fingerprint=cypher_fingerprint,
        )
        self._s.add(row)
        await self._s.flush()
        return row.id

    # ---- mappers -------------------------------------------------
    @staticmethod
    def _detection(r: DetectionRow) -> Detection:
        from sm_contracts import EvidenceItem

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

    @staticmethod
    def _alert(r: AlertRow) -> SecurityAlert:
        return SecurityAlert(
            id=r.id, tenant_id=r.tenant_id, created_at=r.created_at, updated_at=r.updated_at,
            detection_id=r.detection_id, severity=Severity(r.severity), status=r.status,
            title=r.title, summary=r.summary, opened_at=r.opened_at,
            acknowledged_at=r.acknowledged_at, closed_at=r.closed_at,
        )

    @staticmethod
    def _score(r: ThreatScoreRow) -> ThreatScore:
        return ThreatScore(
            id=r.id, tenant_id=r.tenant_id, created_at=r.created_at, updated_at=r.updated_at,
            subject_type=ThreatSubjectType(r.subject_type), subject_id=r.subject_id, score=r.score,
            components=dict(r.components), weights_version=r.weights_version,
            scoring_status=r.scoring_status, computed_at=r.computed_at,
        )
