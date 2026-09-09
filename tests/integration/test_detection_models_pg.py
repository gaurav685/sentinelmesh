"""Phase 5 Unit 1 — real PostgreSQL: the detection-domain tables.

Constraints, the threat_score upsert, the alert cascade, and tenant isolation —
the things a unit test with fakes cannot prove.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from sm_common.db import Anomaly, Database, Detection, SecurityAlert, ThreatScore

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


def _detection(tid: uuid.UUID, **over: object) -> Detection:
    base: dict[str, object] = dict(
        id=uuid.uuid4(), tenant_id=tid, detector="rule", rule_id="rule.x",
        title="t", severity="high", score=0.7, scoring_status="ok", status="new",
        entities=[], technique_ids=[], evidence=[], dedup_key="k",
        first_seen=_NOW, last_seen=_NOW,
    )
    base.update(over)
    return Detection(**base)  # type: ignore[arg-type]


async def test_detection_score_range_is_enforced(clean: Database) -> None:
    tid = await _tenant(clean)
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_detection(tid, score=1.5))


async def test_detection_detector_check(clean: Database) -> None:
    tid = await _tenant(clean)
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_detection(tid, detector="mystery"))


async def test_threat_score_is_one_row_per_subject(clean: Database) -> None:
    tid = await _tenant(clean)
    row = dict(
        tenant_id=tid, subject_type="identity", subject_id="alice", score=0.4,
        components={"rule": 0.4}, weights_version="v1", scoring_status="ok", computed_at=_NOW,
    )
    async with clean.transaction() as s:
        s.add(ThreatScore(id=uuid.uuid4(), **row))  # type: ignore[arg-type]
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(ThreatScore(id=uuid.uuid4(), **row))  # type: ignore[arg-type]


async def test_alert_is_deleted_with_its_detection(clean: Database) -> None:
    tid = await _tenant(clean)
    det = _detection(tid)
    async with clean.transaction() as s:
        s.add(det)
    async with clean.transaction() as s:
        s.add(SecurityAlert(
            id=uuid.uuid4(), tenant_id=tid, detection_id=det.id, severity="high",
            status="open", title="t", opened_at=_NOW,
        ))
    async with clean.transaction() as s:
        await s.execute(text("DELETE FROM detection WHERE id = :id"), {"id": det.id})
    async with clean.transaction() as s:
        remaining = (await s.execute(select(SecurityAlert))).scalars().all()
    assert remaining == []


async def test_tenant_fk_rejects_unknown_tenant(clean: Database) -> None:
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_detection(uuid.uuid4()))


async def test_anomaly_normalized_score_range(clean: Database) -> None:
    tid = await _tenant(clean)
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(Anomaly(
                id=uuid.uuid4(), tenant_id=tid, method="mad_zscore", feature_schema_version="1",
                score=99.0, normalized_score=2.0, threshold=3.0, is_anomaly=True, observed_at=_NOW,
                features={},
            ))
