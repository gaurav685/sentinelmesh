"""`NarrativeRepository` against a real PostgreSQL.

The unit tests use a fake, so the actual SQL — the tenant-scoped
`(tenant_id, chain_id)` upsert and the `narrative` body round trip
through JSONB — is only exercised here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from sm_ai_analyst.narrative import NarrativeBody
from sm_ai_analyst.repository import NarrativeRepository
from sm_common.clock import utcnow
from sm_common.db import Database
from sm_common.db.models import Tenant
from sm_common.ids import uuid7
from sm_contracts import GroundingKind, NarrativeBeat
from sm_contracts.enums import TenantStatus

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC)


async def _seed_tenant(db: Database) -> UUID:
    tenant_id = uuid7()
    slug = f"narrative-test-{tenant_id.hex[:12]}"
    async with db.transaction() as session:
        session.add(Tenant(
            id=tenant_id, slug=slug, name="Narrative Test",
            status=TenantStatus.active.value, settings={},
        ))
    return tenant_id


def _body(**over: object) -> NarrativeBody:
    body = NarrativeBody()
    body.beats = [
        NarrativeBeat(
            at=_NOW, stage="initial_access", title="Initial Access",
            detection_ids=["d1"], technique_ids=["T1110"], detection_count=1,
            tier=GroundingKind.evidence,
        ),
    ]
    body.summary = "The attacker gained a foothold [initial_access]."
    body.cited_refs = ["initial_access"]
    body.confidence = "low"
    for k, v in over.items():
        setattr(body, k, v)
    return body


@pytest.mark.asyncio
async def test_upsert_then_get_round_trips(clean: Database):
    tenant_id = await _seed_tenant(clean)
    chain_id = uuid7()
    repo = NarrativeRepository(clean)

    saved = await repo.upsert(
        tenant_id, chain_id, subject_type="host", subject_id="web01",
        body=_body(), generated_at=utcnow(),
    )
    assert saved.chain_id == chain_id
    assert saved.beats[0].stage.value == "initial_access"

    fetched = await repo.get(tenant_id, chain_id)
    assert fetched is not None
    assert fetched.summary == saved.summary


@pytest.mark.asyncio
async def test_a_second_upsert_for_the_same_chain_replaces_not_duplicates(clean: Database):
    tenant_id = await _seed_tenant(clean)
    chain_id = uuid7()
    repo = NarrativeRepository(clean)

    first = await repo.upsert(
        tenant_id, chain_id, subject_type="host", subject_id="web01",
        body=_body(summary="first pass"), generated_at=utcnow(),
    )
    second = await repo.upsert(
        tenant_id, chain_id, subject_type="host", subject_id="web01",
        body=_body(summary="second pass"), generated_at=utcnow(),
    )
    assert first.id == second.id
    fetched = await repo.get(tenant_id, chain_id)
    assert fetched is not None
    assert fetched.summary == "second pass"


@pytest.mark.asyncio
async def test_get_is_tenant_scoped(clean: Database):
    tenant_id = await _seed_tenant(clean)
    other_tenant_id = await _seed_tenant(clean)
    chain_id = uuid7()
    repo = NarrativeRepository(clean)

    await repo.upsert(
        tenant_id, chain_id, subject_type="host", subject_id="web01",
        body=_body(), generated_at=utcnow(),
    )
    assert await repo.get(other_tenant_id, chain_id) is None
    assert await repo.get(tenant_id, chain_id) is not None


@pytest.mark.asyncio
async def test_simulated_narrative_round_trips(clean: Database):
    tenant_id = await _seed_tenant(clean)
    chain_id = uuid7()
    repo = NarrativeRepository(clean)

    simulated_beats = [
        NarrativeBeat(
            at=_NOW, stage="initial_access", title="Initial Access",
            detection_ids=["d1"], technique_ids=["T1110"], detection_count=1,
            tier=GroundingKind.synthetic,
        ),
    ]
    saved = await repo.upsert(
        tenant_id, chain_id, subject_type="host", subject_id="sim-host-01",
        body=_body(beats=simulated_beats, simulated=True), generated_at=utcnow(),
    )
    assert saved.simulated is True
    assert saved.beats[0].tier == GroundingKind.synthetic
