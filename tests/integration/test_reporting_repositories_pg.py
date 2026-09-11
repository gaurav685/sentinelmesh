"""`ContentRepository` and `ReportRepository` against a real PostgreSQL.

The unit tests use fakes, so the actual SQL — the tenant predicate, the
app-level entity filter over `detection.entities`, and the `report` /
`report_template` round trip through JSONB — is only exercised here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from sm_common.clock import utcnow
from sm_common.db import Database
from sm_common.db.detection_models import Detection as DetectionRow
from sm_common.db.detection_models import ThreatScore as ThreatScoreRow
from sm_common.db.models import Tenant, User
from sm_common.db.report_models import ReportTemplateRow
from sm_common.ids import uuid7
from sm_contracts.enums import TenantStatus, UserStatus
from sm_reporting_service.content_repository import ContentRepository
from sm_reporting_service.repository import ReportBody, ReportRepository

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC)


async def _seed_tenant_and_user(db: Database) -> tuple[UUID, UUID]:
    tenant_id, user_id = uuid7(), uuid7()
    slug = f"reporting-test-{tenant_id.hex[:12]}"
    async with db.transaction() as session:
        session.add(Tenant(
            id=tenant_id, slug=slug, name="Reporting Test",
            status=TenantStatus.active.value, settings={},
        ))
        await session.flush()
        session.add(User(
            id=user_id, tenant_id=tenant_id, email=f"analyst@{slug}.com",
            display_name="Analyst", status=UserStatus.active.value, failed_login_count=0,
        ))
    return tenant_id, user_id


async def _seed_detection(db: Database, tenant_id: UUID, **over: object) -> UUID:
    base: dict[str, object] = dict(
        id=uuid7(), tenant_id=tenant_id, detector="rule", rule_id="r1",
        title="Suspicious login", description="brute force", severity="high",
        score=0.8, scoring_status="ok", status="new",
        entities=[{"kind": "host", "value": "web01"}], technique_ids=["T1110"],
        evidence=[], dedup_key=f"dk-{uuid7()}", first_seen=_NOW, last_seen=_NOW,
    )
    base.update(over)
    row = DetectionRow(**base)  # type: ignore[arg-type]
    async with db.transaction() as session:
        session.add(row)
    return UUID(str(row.id))


@pytest.mark.asyncio
async def test_get_detection_is_tenant_scoped(clean: Database):
    tenant_id, _ = await _seed_tenant_and_user(clean)
    other_tenant_id, _ = await _seed_tenant_and_user(clean)
    det_id = await _seed_detection(clean, tenant_id)

    repo = ContentRepository(clean)
    assert (await repo.get_detection(tenant_id, det_id)) is not None
    assert (await repo.get_detection(other_tenant_id, det_id)) is None


@pytest.mark.asyncio
async def test_list_detections_for_subject_matches_the_entities_list(clean: Database):
    tenant_id, _ = await _seed_tenant_and_user(clean)
    await _seed_detection(clean, tenant_id, entities=[{"kind": "host", "value": "web01"}])
    await _seed_detection(clean, tenant_id, entities=[{"kind": "host", "value": "web02"}])

    repo = ContentRepository(clean)
    matched = await repo.list_detections_for_subject(tenant_id, subject_type="host", subject_id="web01")
    assert len(matched) == 1
    assert matched[0].entities[0].value == "web01"


@pytest.mark.asyncio
async def test_get_threat_score_round_trips(clean: Database):
    tenant_id, _ = await _seed_tenant_and_user(clean)
    async with clean.transaction() as session:
        session.add(ThreatScoreRow(
            id=uuid7(), tenant_id=tenant_id, subject_type="host", subject_id="web01",
            score=0.6, components={"base": 0.6}, weights_version="v1", scoring_status="ok",
            computed_at=utcnow(),
        ))

    repo = ContentRepository(clean)
    score = await repo.get_threat_score(tenant_id, subject_type="host", subject_id="web01")
    assert score is not None
    assert score.score == 0.6

    absent = await repo.get_threat_score(tenant_id, subject_type="host", subject_id="unknown")
    assert absent is None


@pytest.mark.asyncio
async def test_report_create_get_and_save_result_round_trips(clean: Database):
    tenant_id, user_id = await _seed_tenant_and_user(clean)
    repo = ReportRepository(clean)

    report = await repo.create_pending(
        tenant_id, kind="incident", subject_type="host", subject_id="web01",
        title="Test report", requested_by=user_id,
    )
    assert report.status == "pending"

    fetched = await repo.get(tenant_id, report.id)
    assert fetched is not None
    assert fetched.title == "Test report"

    body = ReportBody()
    body.provenance = ["detection-engine"]
    body.evidence = []
    saved = await repo.save_result(
        tenant_id, report.id, status="complete", body=body, missing_sections=[],
        storage_key="tenant/reports/x.pdf", generated_at=utcnow(),
    )
    assert saved.status == "complete"
    assert saved.storage_key == "tenant/reports/x.pdf"
    assert saved.provenance == ["detection-engine"]


@pytest.mark.asyncio
async def test_report_get_is_tenant_scoped(clean: Database):
    tenant_id, user_id = await _seed_tenant_and_user(clean)
    other_tenant_id, _ = await _seed_tenant_and_user(clean)
    repo = ReportRepository(clean)

    report = await repo.create_pending(
        tenant_id, kind="incident", subject_type="host", subject_id="web01",
        title="t", requested_by=user_id,
    )
    assert await repo.get(other_tenant_id, report.id) is None
    assert await repo.get(tenant_id, report.id) is not None


@pytest.mark.asyncio
async def test_template_sections_reads_the_seeded_default(clean: Database):
    async with clean.transaction() as session:
        session.add(ReportTemplateRow(
            id=uuid7(), kind="incident", name="Default incident template", version="1",
            sections=["metadata", "findings"], is_default=True,
        ))

    repo = ReportRepository(clean)
    assert await repo.template_sections("incident") == ["metadata", "findings"]
    assert await repo.template_sections("compliance") == []
