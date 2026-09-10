"""Phase 9 Unit 1 — real PostgreSQL: the api-gateway SOC read repository.

`SqlSocRepository` reads the detection / alert / threat-score / technique-mapping
tables written by other services, always scoped to the caller's tenant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from sm_api_gateway.repositories.soc import SqlSocRepository
from sm_common.db import Database, Detection, SecurityAlert, ThreatScore
from sm_common.db.intel_models import TechniqueMappingRow
from sm_common.ids import uuid7

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC)


async def _tenant(db: Database) -> uuid.UUID:
    tid = uuid.uuid4()
    async with db.transaction() as s:
        await s.execute(
            text("INSERT INTO tenant (id, slug, name, status) VALUES (:id, :slug, 'T', 'active')"),
            {"id": tid, "slug": f"t-{tid.hex[:12]}"},
        )
    return tid


async def _seed(db: Database, tenant: uuid.UUID, *, subject: str = "svc-backup") -> uuid.UUID:
    det_id = uuid7()
    async with db.transaction() as s:
        s.add(Detection(
            id=det_id, tenant_id=tenant, detector="composite", rule_id="rule.auth.failed_burst",
            title="Repeated auth failures", description="12 fails", severity="high", score=0.82,
            scoring_status="ok", status="new",
            entities=[{"kind": "identity", "value": subject}], technique_ids=["T1110"], evidence=[],
            dedup_key="k", first_seen=_NOW, last_seen=_NOW,
        ))
        s.add(SecurityAlert(
            id=uuid7(), tenant_id=tenant, detection_id=det_id, severity="high", status="open",
            title="Brute force", summary="", opened_at=_NOW,
        ))
        s.add(ThreatScore(
            id=uuid7(), tenant_id=tenant, subject_type="identity", subject_id=subject, score=0.7,
            components={"severity": 0.8}, weights_version="v1", scoring_status="ok", computed_at=_NOW,
        ))
        s.add(TechniqueMappingRow(
            id=uuid7(), tenant_id=tenant, subject_type="detection", subject_id=det_id,
            technique_id="T1110", tactic_id="TA0006", confidence="medium", source="rule",
            rationale="named by rule", evidence=[], matrix_version="14.1",
        ))
    return det_id


async def test_reads_are_tenant_scoped(clean: Database) -> None:
    t1, t2 = await _tenant(clean), await _tenant(clean)
    d1 = await _seed(clean, t1)
    await _seed(clean, t2)

    async with clean.session() as s:
        r = SqlSocRepository(s)
        dets = await r.list_detections(t1, limit=50)
        assert [str(d.id) for d in dets] == [str(d1)]
        assert await r.get_detection(t1, d1) is not None
        assert await r.get_detection(t2, d1) is None  # cross-tenant -> None

        alerts = await r.list_alerts(t1, limit=50)
        assert len(alerts) == 1 and alerts[0].status == "open"

        risk = await r.top_risk(t1, limit=10)
        assert [x.subject_id for x in risk] == ["svc-backup"]


async def test_summary_and_heatmap(clean: Database) -> None:
    tenant = await _tenant(clean)
    await _seed(clean, tenant)
    async with clean.session() as s:
        r = SqlSocRepository(s)
        summary = await r.summary(tenant)
        assert summary.open_alerts == 1
        assert summary.detections_24h == 1
        assert summary.top_risk_subjects[0].subject_id == "svc-backup"

        cells = await r.mitre_heatmap(tenant)
        assert [(c.technique_id, c.subject_count) for c in cells] == [("T1110", 1)]


async def test_detections_before_cursor_pages_backwards(clean: Database) -> None:
    tenant = await _tenant(clean)
    await _seed(clean, tenant)
    async with clean.session() as s:
        r = SqlSocRepository(s)
        assert await r.list_detections(tenant, limit=50, before=_NOW - timedelta(days=1)) == []


async def test_entity_timeline_filters_by_subject(clean: Database) -> None:
    tenant = await _tenant(clean)
    await _seed(clean, tenant, subject="alice")
    await _seed(clean, tenant, subject="bob")
    async with clean.session() as s:
        r = SqlSocRepository(s)
        entries = await r.entity_timeline(tenant, "alice", limit=100)
        assert [e.kind for e in entries] == ["detection"]
        assert entries[0].detail["detector"] == "composite"
