"""Phase 13 Unit 2 — real PostgreSQL: `MemoryRepository`.

Covers what the unit tests (fakes) cannot: real upsert-merge semantics, real
pgvector campaign matching, real tenant isolation, and the real retention
sweep's status transitions and deletions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_memory_service.repository import MemoryRepository
from sqlalchemy import text

from sm_common.db import Database

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


async def test_upsert_pattern_merges_and_counts_occurrences(clean: Database) -> None:
    repo = MemoryRepository(clean)
    tenant = await _tenant(clean)

    first = await repo.upsert_pattern(
        tenant, subject_type="host", subject_id="web01", technique_ids=["T1110"],
        source="attack_chain:c1",
    )
    assert first.occurrence_count == 1
    assert first.technique_ids == ["T1110"]

    second = await repo.upsert_pattern(
        tenant, subject_type="host", subject_id="web01", technique_ids=["T1078"],
        source="attack_chain:c2",
    )
    assert second.id == first.id
    assert second.occurrence_count == 2
    assert second.technique_ids == ["T1078", "T1110"]


async def test_patterns_are_tenant_scoped(clean: Database) -> None:
    repo = MemoryRepository(clean)
    tenant_a = await _tenant(clean)
    tenant_b = await _tenant(clean)
    await repo.upsert_pattern(
        tenant_a, subject_type="host", subject_id="web01", technique_ids=["T1110"], source="x"
    )
    assert await repo.list_patterns(tenant_b) == []
    assert len(await repo.list_patterns(tenant_a)) == 1


async def test_attach_chain_to_campaign_groups_similar_chains(clean: Database) -> None:
    repo = MemoryRepository(clean)
    tenant = await _tenant(clean)

    first = await repo.attach_chain_to_campaign(
        tenant, chain_id="c1", technique_ids=["T1110", "T1078"], threshold=0.5,
    )
    assert first.chain_ids == ["c1"]

    # Same technique set -> the same campaign, not a new one.
    second = await repo.attach_chain_to_campaign(
        tenant, chain_id="c2", technique_ids=["T1110", "T1078"], threshold=0.5,
    )
    assert second.id == first.id
    assert set(second.chain_ids) == {"c1", "c2"}

    # A disjoint technique set -> a new campaign.
    third = await repo.attach_chain_to_campaign(
        tenant, chain_id="c3", technique_ids=["T1486", "T1490"], threshold=0.5,
    )
    assert third.id != first.id


async def test_upsert_fingerprint_accumulates_campaigns(clean: Database) -> None:
    repo = MemoryRepository(clean)
    tenant = await _tenant(clean)

    fp1 = await repo.upsert_fingerprint(
        tenant, subject_type="identity", subject_id="svc-backup",
        technique_ids=["T1110"], campaign_id="camp-1",
    )
    assert fp1.campaign_ids == ["camp-1"]

    fp2 = await repo.upsert_fingerprint(
        tenant, subject_type="identity", subject_id="svc-backup",
        technique_ids=["T1078"], campaign_id="camp-2",
    )
    assert fp2.id == fp1.id
    assert fp2.campaign_ids == ["camp-1", "camp-2"]
    assert fp2.technique_ids == ["T1078", "T1110"]


async def test_find_similar_ranks_the_closer_pattern_first(clean: Database) -> None:
    repo = MemoryRepository(clean)
    tenant = await _tenant(clean)
    await repo.upsert_pattern(
        tenant, subject_type="host", subject_id="brute", technique_ids=["T1110", "T1078"],
        source="x",
    )
    await repo.upsert_pattern(
        tenant, subject_type="host", subject_id="ransom", technique_ids=["T1486", "T1490"],
        source="x",
    )
    matches = await repo.find_similar(
        tenant, kind="threat_memory", technique_ids=["T1110", "T1078", "T1021"], limit=5,
    )
    assert matches
    assert matches[0].technique_ids == ["T1078", "T1110"]
    assert matches[0].exact_fallback is False
    assert matches[0].score > matches[-1].score


async def test_retention_sweep_ages_and_deletes(clean: Database) -> None:
    repo = MemoryRepository(clean)
    tenant = await _tenant(clean)
    stale = _NOW - timedelta(days=200)

    await repo.upsert_pattern(
        tenant, subject_type="host", subject_id="old", technique_ids=["T1110"], source="x",
        now=stale,
    )
    await repo.attach_chain_to_campaign(
        tenant, chain_id="c1", technique_ids=["T1110"], now=stale,
    )
    fresh_campaign = await repo.attach_chain_to_campaign(
        tenant, chain_id="c2", technique_ids=["T1595"], now=_NOW,
    )

    counts = await repo.sweep_retention(
        now=_NOW, dormant_after=timedelta(days=14), close_after=timedelta(days=60),
        delete_after=timedelta(days=180),
    )
    assert counts["closed"] == 1
    assert counts["deleted_campaigns"] == 1
    assert counts["deleted_patterns"] == 1

    remaining = await repo.list_campaigns(tenant)
    remaining_ids = {c.id for c in remaining}
    assert fresh_campaign.id in remaining_ids
    assert await repo.list_patterns(tenant) == []
