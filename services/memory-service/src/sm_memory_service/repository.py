"""Threat-memory repository (Phase 13).

Upserts patterns/campaigns/fingerprints, tenant-scoped and never duplicating
the operational/knowledge graph (ADR-011). Similarity search tries a
pgvector nearest-neighbor query first; on any database error it falls back
to a bounded, tenant-scoped Python scan using `sm_ml.memory.cosine_similarity`
— recomputed from each candidate's `technique_ids`, never by reading the
stored `pgvector` column back (its runtime type depends on whether `numpy`
is importable, which `technique_ids` — a plain JSON list — does not).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from sm_common.clock import utcnow
from sm_common.db import AdversaryFingerprintRow, CampaignRow, Database, ThreatMemoryRow
from sm_contracts import AdversaryFingerprint, Campaign, SimilarityMatch, ThreatMemory
from sm_ml.memory import cosine_similarity, technique_feature_vector

__all__ = ["MemoryRepository"]

_log = structlog.get_logger("sm.memory_service.repository")

#: Bound on the Python-side exact-fallback scan — a full-table degrade must
#: still be a bounded query, never an unbounded one (Constitution §8, §10).
_FALLBACK_SCAN_LIMIT = 500
_CAMPAIGN_MATCH_LIMIT = 200
SimilarityKind = Literal["threat_memory", "campaign", "adversary_fingerprint"]


def _merge(existing: Sequence[str], new: Sequence[str]) -> list[str]:
    return sorted(set(existing) | set(new))


def _pattern_out(row: ThreatMemoryRow) -> ThreatMemory:
    return ThreatMemory(
        id=row.id, tenant_id=row.tenant_id, subject_type=row.subject_type,
        subject_id=row.subject_id, pattern_kind=row.pattern_kind,
        technique_ids=list(row.technique_ids), occurrence_count=row.occurrence_count,
        first_seen=row.first_seen, last_seen=row.last_seen, source=row.source,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _campaign_out(row: CampaignRow) -> Campaign:
    return Campaign(
        id=row.id, tenant_id=row.tenant_id, status=row.status,
        chain_ids=list(row.chain_ids), technique_ids=list(row.technique_ids),
        first_seen=row.first_seen, last_seen=row.last_seen,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _fingerprint_out(row: AdversaryFingerprintRow) -> AdversaryFingerprint:
    return AdversaryFingerprint(
        id=row.id, tenant_id=row.tenant_id, subject_type=row.subject_type,
        subject_id=row.subject_id, technique_ids=list(row.technique_ids),
        campaign_ids=list(row.campaign_ids), first_seen=row.first_seen, last_seen=row.last_seen,
        created_at=row.created_at, updated_at=row.updated_at,
    )


class MemoryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- patterns ------------------------------------------------
    async def upsert_pattern(
        self, tenant_id: UUID, *, subject_type: str, subject_id: str,
        technique_ids: Sequence[str], source: str, now: datetime | None = None,
    ) -> ThreatMemory:
        at = now or utcnow()
        async with self._db.transaction() as s:
            row = (
                await s.execute(
                    select(ThreatMemoryRow).where(
                        ThreatMemoryRow.tenant_id == tenant_id,
                        ThreatMemoryRow.subject_type == subject_type,
                        ThreatMemoryRow.subject_id == subject_id,
                        ThreatMemoryRow.pattern_kind == "technique_sequence",
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                merged = sorted(set(technique_ids))
                row = ThreatMemoryRow(
                    tenant_id=tenant_id, subject_type=subject_type, subject_id=subject_id,
                    pattern_kind="technique_sequence", technique_ids=merged,
                    feature_vector=technique_feature_vector(merged),
                    occurrence_count=1, first_seen=at, last_seen=at, source=source,
                )
                s.add(row)
            else:
                row.technique_ids = _merge(row.technique_ids, technique_ids)
                row.feature_vector = technique_feature_vector(row.technique_ids)
                row.occurrence_count += 1
                row.last_seen = at
            await s.flush()
            await s.refresh(row)
        return _pattern_out(row)

    async def list_patterns(
        self, tenant_id: UUID, *, subject_type: str | None = None, subject_id: str | None = None,
        limit: int = 200,
    ) -> list[ThreatMemory]:
        stmt = select(ThreatMemoryRow).where(ThreatMemoryRow.tenant_id == tenant_id)
        if subject_type:
            stmt = stmt.where(ThreatMemoryRow.subject_type == subject_type)
        if subject_id:
            stmt = stmt.where(ThreatMemoryRow.subject_id == subject_id)
        stmt = stmt.order_by(ThreatMemoryRow.last_seen.desc()).limit(min(limit, 500))
        async with self._db.session() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_pattern_out(r) for r in rows]

    # ---- campaigns -----------------------------------------------
    async def find_matching_campaign(
        self, tenant_id: UUID, technique_ids: Sequence[str], *, threshold: float = 0.5,
    ) -> CampaignRow | None:
        """The most similar *active* campaign for this tenant, or `None` if
        nothing clears `threshold` — a fresh campaign is warranted."""
        query_vec = technique_feature_vector(technique_ids)
        best: tuple[CampaignRow, float] | None = None
        try:
            async with self._db.session() as s:
                rows = (
                    await s.execute(
                        select(CampaignRow)
                        .where(CampaignRow.tenant_id == tenant_id, CampaignRow.status == "active")
                        .order_by(CampaignRow.feature_vector.cosine_distance(query_vec))
                        .limit(_CAMPAIGN_MATCH_LIMIT)
                    )
                ).scalars().all()
        except SQLAlchemyError as exc:
            _log.warning("campaign_match_query_failed", error=str(exc))
            rows = await self._campaigns_fallback_scan(tenant_id)
        for row in rows:
            sim = cosine_similarity(technique_feature_vector(row.technique_ids), query_vec)
            if best is None or sim > best[1]:
                best = (row, sim)
        if best is not None and best[1] >= threshold:
            return best[0]
        return None

    async def _campaigns_fallback_scan(self, tenant_id: UUID) -> list[CampaignRow]:
        async with self._db.session() as s:
            return list(
                (
                    await s.execute(
                        select(CampaignRow)
                        .where(CampaignRow.tenant_id == tenant_id, CampaignRow.status == "active")
                        .limit(_FALLBACK_SCAN_LIMIT)
                    )
                ).scalars().all()
            )

    async def attach_chain_to_campaign(
        self, tenant_id: UUID, *, chain_id: str, technique_ids: Sequence[str],
        threshold: float = 0.5, now: datetime | None = None,
    ) -> Campaign:
        """Upsert the chain into its best-matching active campaign, or start
        a new one. Returns the resulting campaign."""
        at = now or utcnow()
        matched = await self.find_matching_campaign(tenant_id, technique_ids, threshold=threshold)
        async with self._db.transaction() as s:
            if matched is not None:
                row = await s.get(CampaignRow, matched.id)
                assert row is not None
                if chain_id not in row.chain_ids:
                    row.chain_ids = [*row.chain_ids, chain_id]
                row.technique_ids = _merge(row.technique_ids, technique_ids)
                row.feature_vector = technique_feature_vector(row.technique_ids)
                row.last_seen = at
                if row.status == "dormant":
                    row.status = "active"
            else:
                merged = sorted(set(technique_ids))
                row = CampaignRow(
                    tenant_id=tenant_id, status="active", chain_ids=[chain_id],
                    technique_ids=merged, feature_vector=technique_feature_vector(merged),
                    first_seen=at, last_seen=at,
                )
                s.add(row)
            await s.flush()
            await s.refresh(row)
        return _campaign_out(row)

    async def get_campaign(self, tenant_id: UUID, campaign_id: UUID) -> Campaign | None:
        async with self._db.session() as s:
            row = (
                await s.execute(
                    select(CampaignRow).where(
                        CampaignRow.tenant_id == tenant_id, CampaignRow.id == campaign_id
                    )
                )
            ).scalar_one_or_none()
        return _campaign_out(row) if row is not None else None

    async def list_campaigns(
        self, tenant_id: UUID, *, status: str | None = None, limit: int = 200,
    ) -> list[Campaign]:
        stmt = select(CampaignRow).where(CampaignRow.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(CampaignRow.status == status)
        stmt = stmt.order_by(CampaignRow.last_seen.desc()).limit(min(limit, 500))
        async with self._db.session() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_campaign_out(r) for r in rows]

    # ---- adversary fingerprints ------------------------------------
    async def upsert_fingerprint(
        self, tenant_id: UUID, *, subject_type: str, subject_id: str,
        technique_ids: Sequence[str], campaign_id: str, now: datetime | None = None,
    ) -> AdversaryFingerprint:
        at = now or utcnow()
        async with self._db.transaction() as s:
            row = (
                await s.execute(
                    select(AdversaryFingerprintRow).where(
                        AdversaryFingerprintRow.tenant_id == tenant_id,
                        AdversaryFingerprintRow.subject_type == subject_type,
                        AdversaryFingerprintRow.subject_id == subject_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                merged = sorted(set(technique_ids))
                row = AdversaryFingerprintRow(
                    tenant_id=tenant_id, subject_type=subject_type, subject_id=subject_id,
                    technique_ids=merged, campaign_ids=[campaign_id],
                    feature_vector=technique_feature_vector(merged),
                    first_seen=at, last_seen=at,
                )
                s.add(row)
            else:
                row.technique_ids = _merge(row.technique_ids, technique_ids)
                row.feature_vector = technique_feature_vector(row.technique_ids)
                if campaign_id not in row.campaign_ids:
                    row.campaign_ids = [*row.campaign_ids, campaign_id]
                row.last_seen = at
            await s.flush()
            await s.refresh(row)
        return _fingerprint_out(row)

    async def get_fingerprint(
        self, tenant_id: UUID, *, subject_type: str, subject_id: str,
    ) -> AdversaryFingerprint | None:
        async with self._db.session() as s:
            row = (
                await s.execute(
                    select(AdversaryFingerprintRow).where(
                        AdversaryFingerprintRow.tenant_id == tenant_id,
                        AdversaryFingerprintRow.subject_type == subject_type,
                        AdversaryFingerprintRow.subject_id == subject_id,
                    )
                )
            ).scalar_one_or_none()
        return _fingerprint_out(row) if row is not None else None

    async def list_fingerprints(
        self, tenant_id: UUID, *, exclude_subject_type: str | None = None,
        exclude_subject_id: str | None = None, limit: int = 200,
    ) -> list[AdversaryFingerprint]:
        stmt = select(AdversaryFingerprintRow).where(AdversaryFingerprintRow.tenant_id == tenant_id)
        if exclude_subject_type is not None and exclude_subject_id is not None:
            stmt = stmt.where(
                ~(
                    (AdversaryFingerprintRow.subject_type == exclude_subject_type)
                    & (AdversaryFingerprintRow.subject_id == exclude_subject_id)
                )
            )
        stmt = stmt.order_by(AdversaryFingerprintRow.last_seen.desc()).limit(min(limit, 500))
        async with self._db.session() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_fingerprint_out(r) for r in rows]

    # ---- similarity retrieval --------------------------------------
    async def find_similar(
        self, tenant_id: UUID, *, kind: SimilarityKind, technique_ids: Sequence[str], limit: int = 10,
    ) -> list[SimilarityMatch]:
        query_vec = technique_feature_vector(technique_ids)
        model: type[ThreatMemoryRow] | type[CampaignRow] | type[AdversaryFingerprintRow]
        if kind == "threat_memory":
            model = ThreatMemoryRow
        elif kind == "campaign":
            model = CampaignRow
        else:
            model = AdversaryFingerprintRow
        exact_fallback = False
        try:
            async with self._db.session() as s:
                rows = (
                    await s.execute(
                        select(model)
                        .where(model.tenant_id == tenant_id)
                        .order_by(model.feature_vector.cosine_distance(query_vec))
                        .limit(min(limit, 100))
                    )
                ).scalars().all()
        except SQLAlchemyError as exc:
            _log.warning("similarity_query_failed", kind=kind, error=str(exc))
            exact_fallback = True
            async with self._db.session() as s:
                rows = (
                    await s.execute(
                        select(model).where(model.tenant_id == tenant_id).limit(_FALLBACK_SCAN_LIMIT)
                    )
                ).scalars().all()
            rows = sorted(
                rows,
                key=lambda r: cosine_similarity(
                    technique_feature_vector(r.technique_ids), query_vec  # type: ignore[attr-defined]
                ),
                reverse=True,
            )[:limit]
        return [
            SimilarityMatch(
                kind=kind, id=r.id,  # type: ignore[attr-defined]
                score=cosine_similarity(
                    technique_feature_vector(r.technique_ids), query_vec  # type: ignore[attr-defined]
                ),
                technique_ids=list(r.technique_ids), last_seen=r.last_seen,  # type: ignore[attr-defined]
                exact_fallback=exact_fallback,
            )
            for r in rows
        ]

    # ---- retention / deletion lifecycle -----------------------------
    async def sweep_retention(
        self, *, now: datetime | None = None, dormant_after: timedelta, close_after: timedelta,
        delete_after: timedelta,
    ) -> dict[str, int]:
        """Age out threat memory: campaigns go active -> dormant -> closed on
        inactivity; patterns, fingerprints, and closed campaigns past
        `delete_after` are deleted outright. Never touches another tenant's
        rows differently — every threshold is by `last_seen`, tenant-blind by
        design (retention is a platform policy, not a per-tenant one)."""
        at = now or utcnow()
        counts = {"dormant": 0, "closed": 0, "deleted_campaigns": 0, "deleted_patterns": 0,
                  "deleted_fingerprints": 0}
        async with self._db.transaction() as s:
            dormant_cutoff = at - dormant_after
            close_cutoff = at - close_after
            delete_cutoff = at - delete_after

            active = (
                await s.execute(select(CampaignRow).where(CampaignRow.status == "active"))
            ).scalars().all()
            for row in active:
                if row.last_seen < close_cutoff:
                    row.status = "closed"
                    counts["closed"] += 1
                elif row.last_seen < dormant_cutoff:
                    row.status = "dormant"
                    counts["dormant"] += 1
            # `autoflush=False` (platform-wide, see `session.py`) — the status
            # transitions above are pending in Python only; flush so the
            # deletes below (plain Core statements, not autoflush-aware) see
            # a campaign this same sweep just closed.
            await s.flush()

            deleted_campaigns = await s.execute(
                delete(CampaignRow).where(
                    CampaignRow.status == "closed", CampaignRow.last_seen < delete_cutoff
                )
            )
            counts["deleted_campaigns"] = deleted_campaigns.rowcount or 0  # type: ignore[attr-defined]

            deleted_patterns = await s.execute(
                delete(ThreatMemoryRow).where(ThreatMemoryRow.last_seen < delete_cutoff)
            )
            counts["deleted_patterns"] = deleted_patterns.rowcount or 0  # type: ignore[attr-defined]

            deleted_fps = await s.execute(
                delete(AdversaryFingerprintRow).where(AdversaryFingerprintRow.last_seen < delete_cutoff)
            )
            counts["deleted_fingerprints"] = deleted_fps.rowcount or 0  # type: ignore[attr-defined]
        return counts
