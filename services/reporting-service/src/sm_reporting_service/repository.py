"""Report + report-template persistence (Phase 14).

A `Report` row stores everything but its own identity/status columns as one
JSONB `body` — see `sm_common.db.report_models` for why: a report is an
immutable, point-in-time snapshot, never queried by its internal fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from sm_common.db import Database, ReportRow, ReportTemplateRow
from sm_contracts import (
    GroundedStatement,
    Report,
    ReportAsset,
    ReportKind,
    ReportStatus,
    ReportTimelineEntry,
    ThreatSubjectType,
)

__all__ = ["ReportBody", "ReportRepository"]


class ReportBody:
    """The mutable content a `ReportGenerator` assembles before it is
    persisted — everything `Report` carries except its identity/status
    columns, which the repository owns."""

    def __init__(self) -> None:
        self.incident_metadata: dict[str, str] = {}
        self.timeline: list[ReportTimelineEntry] = []
        self.affected_assets: list[ReportAsset] = []
        self.detection_ids: list[str] = []
        self.evidence: list[GroundedStatement] = []
        self.chain_ids: list[str] = []
        self.technique_ids: list[str] = []
        self.threat_score: float | None = None
        self.findings: list[GroundedStatement] = []
        self.recommendations: list[GroundedStatement] = []
        self.confidence: float | None = None
        self.provenance: list[str] = []

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_metadata": self.incident_metadata,
            "timeline": [e.model_dump(mode="json") for e in self.timeline],
            "affected_assets": [e.model_dump(mode="json") for e in self.affected_assets],
            "detection_ids": self.detection_ids,
            "evidence": [e.model_dump(mode="json") for e in self.evidence],
            "chain_ids": self.chain_ids,
            "technique_ids": self.technique_ids,
            "threat_score": self.threat_score,
            "findings": [e.model_dump(mode="json") for e in self.findings],
            "recommendations": [e.model_dump(mode="json") for e in self.recommendations],
            "confidence": self.confidence,
            "provenance": self.provenance,
        }


def _report_out(row: ReportRow) -> Report:
    body = dict(row.body)
    return Report(
        id=row.id, tenant_id=row.tenant_id, created_at=row.created_at, updated_at=row.updated_at,
        kind=row.kind, status=row.status, subject_type=ThreatSubjectType(row.subject_type),
        subject_id=row.subject_id, title=row.title, requested_by=row.requested_by,
        generated_at=row.generated_at,
        incident_metadata=dict(body.get("incident_metadata") or {}),
        timeline=[ReportTimelineEntry.model_validate(e) for e in body.get("timeline") or []],
        affected_assets=[ReportAsset.model_validate(e) for e in body.get("affected_assets") or []],
        detection_ids=list(body.get("detection_ids") or []),
        evidence=[GroundedStatement.model_validate(e) for e in body.get("evidence") or []],
        chain_ids=list(body.get("chain_ids") or []),
        technique_ids=list(body.get("technique_ids") or []),
        threat_score=body.get("threat_score"),
        findings=[GroundedStatement.model_validate(e) for e in body.get("findings") or []],
        recommendations=[GroundedStatement.model_validate(e) for e in body.get("recommendations") or []],
        confidence=body.get("confidence"),
        provenance=list(body.get("provenance") or []),
        missing_sections=list(row.missing_sections),
        storage_key=row.storage_key,
    )


class ReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def default_template_id(self, kind: str) -> UUID | None:
        stmt = select(ReportTemplateRow.id).where(
            ReportTemplateRow.kind == kind, ReportTemplateRow.is_default.is_(True)
        )
        async with self._db.session() as s:
            return (await s.execute(stmt)).scalar_one_or_none()

    async def template_sections(self, kind: str) -> list[str]:
        stmt = select(ReportTemplateRow.sections).where(
            ReportTemplateRow.kind == kind, ReportTemplateRow.is_default.is_(True)
        )
        async with self._db.session() as s:
            sections = (await s.execute(stmt)).scalar_one_or_none()
        return list(sections) if sections else []

    async def create_pending(
        self, tenant_id: UUID, *, kind: ReportKind, subject_type: str, subject_id: str,
        title: str, requested_by: UUID,
    ) -> Report:
        template_id = await self.default_template_id(kind)
        row = ReportRow(
            tenant_id=tenant_id, kind=kind, status="pending", subject_type=subject_type,
            subject_id=subject_id, title=title, requested_by=requested_by, template_id=template_id,
        )
        async with self._db.transaction() as s:
            s.add(row)
            await s.flush()
            await s.refresh(row)
        return _report_out(row)

    async def get(self, tenant_id: UUID, report_id: UUID) -> Report | None:
        async with self._db.session() as s:
            row = await s.get(ReportRow, report_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return _report_out(row)

    async def save_result(
        self, tenant_id: UUID, report_id: UUID, *, status: ReportStatus, body: ReportBody,
        missing_sections: list[str], storage_key: str | None, generated_at: datetime,
    ) -> Report:
        async with self._db.transaction() as s:
            row = await s.get(ReportRow, report_id)
            assert row is not None and row.tenant_id == tenant_id
            row.status = status
            row.body = body.as_dict()
            row.missing_sections = missing_sections
            row.storage_key = storage_key
            row.generated_at = generated_at
            await s.flush()
            await s.refresh(row)
        return _report_out(row)
