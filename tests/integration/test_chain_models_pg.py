"""Phase 7 Unit 1 — real PostgreSQL: the attack-chain tables."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from sm_common.db import AttackChainRow, AttackChainStageRow, Database

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


def _chain(tenant_id: uuid.UUID, **over: object) -> AttackChainRow:
    base: dict[str, object] = dict(
        id=uuid.uuid4(), tenant_id=tenant_id, subject_type="identity", subject_id="alice",
        status="active", window_start=_NOW, first_seen=_NOW, last_seen=_NOW,
        distinct_stage_count=2, progression=0.5, confidence=0.6, score=0.55,
        score_version="v1", scoring_status="ok", technique_ids=["T1110"], detection_count=3,
    )
    base.update(over)
    return AttackChainRow(**base)  # type: ignore[arg-type]


async def test_chain_is_unique_per_subject_and_window(clean: Database) -> None:
    tid = await _tenant(clean)
    async with clean.transaction() as s:
        s.add(_chain(tid))
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_chain(tid, id=uuid.uuid4()))


async def test_chain_score_and_status_checks(clean: Database) -> None:
    tid = await _tenant(clean)
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_chain(tid, score=1.5))
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_chain(tid, status="confirmed"))  # not a ChainStatus value


async def test_stage_is_unique_per_chain_and_cascades(clean: Database) -> None:
    tid = await _tenant(clean)
    chain = _chain(tid)
    async with clean.transaction() as s:
        s.add(chain)
    stage = dict(
        chain_id=chain.id, tenant_id=tid, stage="credential_access", stage_order=7,
        detection_ids=[str(uuid.uuid4())], technique_ids=["T1110"], max_severity="high",
        detection_count=1, first_seen=_NOW, last_seen=_NOW,
    )
    async with clean.transaction() as s:
        s.add(AttackChainStageRow(id=uuid.uuid4(), **stage))  # type: ignore[arg-type]
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(AttackChainStageRow(id=uuid.uuid4(), **stage))  # type: ignore[arg-type]

    async with clean.transaction() as s:
        await s.execute(text("DELETE FROM attack_chain WHERE id = :i"), {"i": chain.id})
        n = (await s.execute(text("SELECT count(*) FROM attack_chain_stage"))).scalar_one()
    assert n == 0  # ON DELETE CASCADE


async def test_stage_rejects_an_unknown_stage_value(clean: Database) -> None:
    tid = await _tenant(clean)
    chain = _chain(tid)
    async with clean.transaction() as s:
        s.add(chain)
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(AttackChainStageRow(
                id=uuid.uuid4(), chain_id=chain.id, tenant_id=tid, stage="pivoting", stage_order=5,
                max_severity="low", detection_count=0, first_seen=_NOW, last_seen=_NOW,
            ))
