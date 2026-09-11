"""Phase 13 Unit 1 — real PostgreSQL: threat-memory tables + pgvector similarity.

Proves the schema choice (an `hnsw`/`vector_cosine_ops` index per table) before
`memory-service`'s repository is built on top of it: a DB-side pgvector
nearest-neighbor query and the Python-side exact fallback
(`sm_ml.memory.cosine_similarity`) agree on ordering, tenant scoping holds,
and the CHECK constraints reject an out-of-vocabulary value at the database
layer regardless of any application-level validation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from sm_common.db import AdversaryFingerprintRow, CampaignRow, Database, ThreatMemoryRow
from sm_ml.memory import cosine_similarity, technique_feature_vector

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


def _memory(tenant_id: uuid.UUID, subject_id: str, technique_ids: list[str], **over: object) -> ThreatMemoryRow:
    base: dict[str, object] = dict(
        tenant_id=tenant_id, subject_type="host", subject_id=subject_id,
        pattern_kind="technique_sequence", technique_ids=technique_ids,
        feature_vector=technique_feature_vector(technique_ids),
        first_seen=_NOW, last_seen=_NOW, source="attack_chain:fixture",
    )
    base.update(over)
    return ThreatMemoryRow(**base)  # type: ignore[arg-type]


async def test_pgvector_nearest_neighbor_agrees_with_the_python_fallback(clean: Database) -> None:
    tenant = await _tenant(clean)
    brute_force = ["T1110", "T1078"]
    ransomware = ["T1486", "T1490"]
    query = technique_feature_vector(["T1110", "T1078", "T1021"])  # closest to brute_force

    async with clean.transaction() as s:
        s.add_all(
            [
                _memory(tenant, "host-a", brute_force),
                _memory(tenant, "host-b", ransomware),
            ]
        )

    async with clean.session() as s:
        rows = (
            await s.execute(
                select(ThreatMemoryRow)
                .where(ThreatMemoryRow.tenant_id == tenant)
                .order_by(ThreatMemoryRow.feature_vector.cosine_distance(query))
                .limit(1)
            )
        ).scalars().all()
    assert rows[0].subject_id == "host-a"

    # The Python exact-fallback ranks the same two candidates the same way.
    sims = {
        "host-a": cosine_similarity(technique_feature_vector(brute_force), query),
        "host-b": cosine_similarity(technique_feature_vector(ransomware), query),
    }
    assert max(sims, key=lambda k: sims[k]) == "host-a"


async def test_threat_memory_is_tenant_scoped(clean: Database) -> None:
    tenant_a = await _tenant(clean)
    tenant_b = await _tenant(clean)
    async with clean.transaction() as s:
        s.add(_memory(tenant_a, "host-a", ["T1110"]))

    async with clean.session() as s:
        for_b = (
            await s.execute(select(ThreatMemoryRow).where(ThreatMemoryRow.tenant_id == tenant_b))
        ).scalars().all()
    assert for_b == []


async def test_threat_memory_upsert_key_is_unique_per_subject_and_pattern(clean: Database) -> None:
    tenant = await _tenant(clean)
    async with clean.transaction() as s:
        s.add(_memory(tenant, "host-a", ["T1110"]))
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_memory(tenant, "host-a", ["T1078"]))


async def test_threat_memory_rejects_an_unknown_subject_type(clean: Database) -> None:
    tenant = await _tenant(clean)
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(_memory(tenant, "host-a", ["T1110"], subject_type="printer"))


async def test_campaign_rejects_an_unknown_status(clean: Database) -> None:
    tenant = await _tenant(clean)
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(
                CampaignRow(
                    tenant_id=tenant, status="rampaging", chain_ids=[], technique_ids=["T1110"],
                    feature_vector=technique_feature_vector(["T1110"]), first_seen=_NOW, last_seen=_NOW,
                )
            )


async def test_adversary_fingerprint_is_unique_per_subject(clean: Database) -> None:
    tenant = await _tenant(clean)
    async with clean.transaction() as s:
        s.add(
            AdversaryFingerprintRow(
                tenant_id=tenant, subject_type="identity", subject_id="svc-backup",
                technique_ids=["T1110"], campaign_ids=[],
                feature_vector=technique_feature_vector(["T1110"]), first_seen=_NOW, last_seen=_NOW,
            )
        )
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            s.add(
                AdversaryFingerprintRow(
                    tenant_id=tenant, subject_type="identity", subject_id="svc-backup",
                    technique_ids=["T1078"], campaign_ids=[],
                    feature_vector=technique_feature_vector(["T1078"]), first_seen=_NOW, last_seen=_NOW,
                )
            )
