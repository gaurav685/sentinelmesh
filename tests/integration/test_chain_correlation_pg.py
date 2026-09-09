"""Phase 7 Unit 2 — real PostgreSQL: attack-chain correlation.

Chain construction, kill-chain ordering, out-of-order events, duplicate
detections, incomplete chains, the tumbling window, and tenant isolation — all
against a real database (JSONB set semantics, the deterministic id, the unique
constraints).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_correlation_engine.chains import ChainRepository
from sm_correlation_engine.staging import StagedDetection
from sqlalchemy import text

from sm_common.db import Database
from sm_contracts import AttackStage, ChainStatus, ScoringStatus, Severity, ThreatSubjectType

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 9, 9, 9, 0, 0, tzinfo=UTC)


async def _tenant(db: Database) -> uuid.UUID:
    tid = uuid.uuid4()
    async with db.transaction() as s:
        await s.execute(
            text("INSERT INTO tenant (id, slug, name, status) VALUES (:id, :slug, 'T', 'active')"),
            {"id": tid, "slug": f"t-{tid.hex[:12]}"},
        )
    return tid


def _staged(
    stage: AttackStage, *, at: datetime, technique: str, severity: Severity = Severity.medium,
    score: float = 0.6, ti: bool = False, degraded: bool = False,
    detection_id: str | None = None,
) -> StagedDetection:
    from sm_contracts import STAGE_ORDER

    return StagedDetection(
        detection_id=detection_id or str(uuid.uuid4()),
        stage=stage, stage_order=STAGE_ORDER[stage], technique_ids=(technique,),
        severity=severity, detection_score=score,
        scoring_status=ScoringStatus.degraded if degraded else ScoringStatus.ok,
        occurred_at=at, ti_corroborated=ti,
    )


def _repo(db: Database, *, window: int = 86_400, dormant: int = 21_600) -> ChainRepository:
    return ChainRepository(db, window_seconds=window, dormant_seconds=dormant)


async def test_multi_stage_chain_is_built_in_kill_chain_order(clean: Database) -> None:
    repo = _repo(clean)
    tid = await _tenant(clean)
    kw = dict(tenant_id=tid, subject_type=ThreatSubjectType.identity, subject_id="alice")

    await repo.correlate(_staged(AttackStage.credential_access, at=_T0, technique="T1110"),
                         now=_T0 + timedelta(minutes=1), **kw)
    await repo.correlate(_staged(AttackStage.lateral_movement, at=_T0 + timedelta(minutes=2),
                                 technique="T1021"), now=_T0 + timedelta(minutes=3), **kw)
    last = await repo.correlate(_staged(AttackStage.exfiltration, at=_T0 + timedelta(minutes=4),
                                        technique="T1048", severity=Severity.high),
                                now=_T0 + timedelta(minutes=5), **kw)

    chain = last.chain
    assert chain.distinct_stage_count == 3
    assert [s.stage for s in chain.stages] == [
        AttackStage.credential_access, AttackStage.lateral_movement, AttackStage.exfiltration
    ]
    assert chain.progression == round(13 / 14, 6)  # exfiltration is kill-chain position 12
    assert chain.status is ChainStatus.active
    assert "out_of_order_observed" not in chain.notes
    assert last.payload.latest_stage is AttackStage.exfiltration


async def test_duplicate_detection_is_idempotent(clean: Database) -> None:
    repo = _repo(clean)
    tid = await _tenant(clean)
    kw = dict(tenant_id=tid, subject_type=ThreatSubjectType.identity, subject_id="bob")
    det_id = str(uuid.uuid4())

    first = await repo.correlate(
        _staged(AttackStage.credential_access, at=_T0, technique="T1110", detection_id=det_id),
        now=_T0, **kw,
    )
    again = await repo.correlate(
        _staged(AttackStage.credential_access, at=_T0, technique="T1110", detection_id=det_id),
        now=_T0, **kw,
    )
    assert first.chain.id == again.chain.id
    assert again.new_detection is False
    assert again.chain.detection_count == 1
    async with clean.transaction() as s:
        n = (await s.execute(text("SELECT count(*) FROM attack_chain_stage WHERE chain_id = :c"),
                             {"c": again.chain.id})).scalar_one()
    assert n == 1


async def test_out_of_order_events_reshape_the_chain_and_are_flagged(clean: Database) -> None:
    repo = _repo(clean)
    tid = await _tenant(clean)
    kw = dict(tenant_id=tid, subject_type=ThreatSubjectType.identity, subject_id="carol")

    # exfiltration happens first in time, then credential-access — the activity
    # ran backwards down the kill chain, which is the out-of-order signal.
    await repo.correlate(_staged(AttackStage.exfiltration, at=_T0, technique="T1048"),
                         now=_T0 + timedelta(minutes=1), **kw)
    out = await repo.correlate(_staged(AttackStage.credential_access, at=_T0 + timedelta(minutes=10),
                                       technique="T1110"), now=_T0 + timedelta(minutes=11), **kw)

    assert out.chain.first_seen == _T0
    assert "out_of_order_observed" in out.chain.notes
    # confidence is discounted versus a clean forward-ordered chain
    forward = _repo(clean)
    tid2 = await _tenant(clean)
    kw2 = dict(tenant_id=tid2, subject_type=ThreatSubjectType.identity, subject_id="carol")
    await forward.correlate(_staged(AttackStage.credential_access, at=_T0, technique="T1110"),
                            now=_T0, **kw2)
    fwd = await forward.correlate(_staged(AttackStage.exfiltration, at=_T0 + timedelta(minutes=10),
                                          technique="T1048"), now=_T0 + timedelta(minutes=11), **kw2)
    assert out.chain.confidence < fwd.chain.confidence


async def test_a_single_detection_is_an_incomplete_forming_chain(clean: Database) -> None:
    repo = _repo(clean)
    tid = await _tenant(clean)
    upd = await repo.correlate(
        _staged(AttackStage.credential_access, at=_T0, technique="T1110"),
        tenant_id=tid, subject_type=ThreatSubjectType.identity, subject_id="dave", now=_T0,
    )
    assert upd.chain.status is ChainStatus.forming
    assert upd.chain.distinct_stage_count == 1
    assert upd.chain.confidence < 0.5
    assert upd.chain.progression == round(8 / 14, 6)


async def test_dormant_when_no_new_evidence_within_the_window(clean: Database) -> None:
    repo = _repo(clean, dormant=3600)
    tid = await _tenant(clean)
    kw = dict(tenant_id=tid, subject_type=ThreatSubjectType.identity, subject_id="erin")
    await repo.correlate(_staged(AttackStage.credential_access, at=_T0, technique="T1110"),
                         now=_T0, **kw)
    later = await repo.correlate(_staged(AttackStage.lateral_movement, at=_T0 + timedelta(minutes=5),
                                         technique="T1021"),
                                 now=_T0 + timedelta(hours=3), **kw)
    assert later.chain.status is ChainStatus.dormant


async def test_detections_outside_the_window_form_separate_chains(clean: Database) -> None:
    repo = _repo(clean, window=3600)
    tid = await _tenant(clean)
    kw = dict(tenant_id=tid, subject_type=ThreatSubjectType.identity, subject_id="frank")
    a = await repo.correlate(_staged(AttackStage.credential_access, at=_T0, technique="T1110"),
                             now=_T0, **kw)
    b = await repo.correlate(_staged(AttackStage.lateral_movement, at=_T0 + timedelta(hours=2),
                                     technique="T1021"), now=_T0 + timedelta(hours=2), **kw)
    assert a.chain.id != b.chain.id
    listed = await repo.list_chains(tid)
    assert len(listed) == 2


async def test_chains_do_not_leak_across_tenants(clean: Database) -> None:
    repo = _repo(clean)
    t1, t2 = await _tenant(clean), await _tenant(clean)
    await repo.correlate(_staged(AttackStage.credential_access, at=_T0, technique="T1110"),
                         tenant_id=t1, subject_type=ThreatSubjectType.identity, subject_id="alice",
                         now=_T0)
    await repo.correlate(_staged(AttackStage.exfiltration, at=_T0, technique="T1048"),
                         tenant_id=t2, subject_type=ThreatSubjectType.identity, subject_id="alice",
                         now=_T0)
    assert {c.subject_id for c in await repo.list_chains(t1)} == {"alice"}
    assert len(await repo.list_chains(t1)) == 1
    assert len(await repo.list_chains(t2)) == 1
    # a t1 caller cannot fetch a t2 chain by id
    t2_chain = (await repo.list_chains(t2))[0]
    assert await repo.get_chain(t1, t2_chain.id) is None


async def test_ti_corroboration_is_monotonic_and_raises_the_score(clean: Database) -> None:
    repo = _repo(clean)
    tid = await _tenant(clean)
    kw = dict(tenant_id=tid, subject_type=ThreatSubjectType.identity, subject_id="grace")
    base = await repo.correlate(_staged(AttackStage.credential_access, at=_T0, technique="T1110"),
                                now=_T0, **kw)
    ti = await repo.correlate(
        _staged(AttackStage.unknown, at=_T0 + timedelta(minutes=1), technique="T1110", ti=True),
        now=_T0 + timedelta(minutes=1), **kw,
    )
    assert ti.chain.ti_corroborated is True
    assert ti.chain.score > base.chain.score
    # a later non-TI detection does not clear the flag
    after = await repo.correlate(_staged(AttackStage.lateral_movement, at=_T0 + timedelta(minutes=2),
                                         technique="T1021"), now=_T0 + timedelta(minutes=2), **kw)
    assert after.chain.ti_corroborated is True


async def test_degraded_member_marks_the_chain_score_degraded(clean: Database) -> None:
    repo = _repo(clean)
    tid = await _tenant(clean)
    upd = await repo.correlate(
        _staged(AttackStage.credential_access, at=_T0, technique="T1110", degraded=True),
        tenant_id=tid, subject_type=ThreatSubjectType.identity, subject_id="heidi", now=_T0,
    )
    assert upd.chain.scoring_status is ScoringStatus.degraded
