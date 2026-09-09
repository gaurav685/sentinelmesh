"""Phase 6 Unit 1 — real PostgreSQL: the threat-intel + MITRE tables."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from sm_common.db import (
    AttackTacticRow,
    AttackTechniqueRow,
    Database,
    TechniqueMappingRow,
    ThreatIndicatorRow,
    TiSourceRow,
)

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


def _indicator(**over: object) -> ThreatIndicatorRow:
    base: dict[str, object] = dict(
        id=uuid.uuid4(), type="ipv4", value="1.2.3.4", source="fixture:demo",
        confidence="high", reputation=0.9, first_seen=_NOW, last_seen=_NOW,
        provenance={"provider": "fixture:demo", "source_kind": "fixture"},
        dedup_key="global|ipv4|1.2.3.4",
    )
    base.update(over)
    return ThreatIndicatorRow(**base)  # type: ignore[arg-type]


async def test_indicator_dedup_key_is_unique(clean: Database) -> None:
    async with clean.transaction() as s:
        s.add(_indicator())
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_indicator(id=uuid.uuid4()))


async def test_indicator_reputation_and_type_checks(clean: Database) -> None:
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_indicator(reputation=2.0))
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_indicator(type="carrier_pigeon", dedup_key="global|x|y"))


async def test_ti_source_ttl_and_name_unique(clean: Database) -> None:
    async with clean.transaction() as s:
        s.add(TiSourceRow(id=uuid.uuid4(), name="urlhaus", kind="feed", enabled=True, ttl_seconds=3600))
    with pytest.raises(IntegrityError):  # ttl < 60
        async with clean.transaction() as s:
            s.add(TiSourceRow(id=uuid.uuid4(), name="x", kind="feed", enabled=True, ttl_seconds=10))


async def test_technique_mapping_is_unique_per_subject_technique_source(clean: Database) -> None:
    tid = await _tenant(clean)
    subject = uuid.uuid4()
    row = dict(
        tenant_id=tid, subject_type="detection", subject_id=subject, technique_id="T1110",
        tactic_id="TA0006", confidence="medium", source="rule",
        rationale="12 failed logins", evidence=[], matrix_version="14.1",
    )
    async with clean.transaction() as s:
        s.add(TechniqueMappingRow(id=uuid.uuid4(), **row))  # type: ignore[arg-type]
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(TechniqueMappingRow(id=uuid.uuid4(), **row))  # type: ignore[arg-type]


async def test_attack_catalog_is_global(clean: Database) -> None:
    async with clean.transaction() as s:
        s.add(AttackTacticRow(
            tactic_id="TA0006", name="Credential Access", shortname="credential-access",
            matrix_version="14.1",
        ))
        s.add(AttackTechniqueRow(
            technique_id="T1110", name="Brute Force", tactic_ids=["TA0006"],
            matrix_version="14.1",
        ))
    async with clean.transaction() as s:
        n = (await s.execute(text("SELECT count(*) FROM attack_technique"))).scalar_one()
    assert n == 1
