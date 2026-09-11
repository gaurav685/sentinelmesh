"""Narrative persistence (Phase 14; req 33).

One row per attack chain, upserted on every `GET .../narrative` — see
`sm_common.db.narrative_models` for why the body is stored whole as
JSONB rather than normalized.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from sm_common.db import Database, NarrativeRow
from sm_contracts import Narrative, NarrativeBeat, ThreatSubjectType

from .narrative import NarrativeBody

__all__ = ["NarrativeRepository"]


def _narrative_out(row: NarrativeRow) -> Narrative:
    body = dict(row.body)
    return Narrative(
        id=row.id, tenant_id=row.tenant_id, created_at=row.created_at, updated_at=row.updated_at,
        chain_id=row.chain_id, subject_type=ThreatSubjectType(row.subject_type),
        subject_id=row.subject_id, generated_at=row.generated_at,
        beats=[NarrativeBeat.model_validate(b) for b in body.get("beats") or []],
        summary=body.get("summary") or "",
        cited_refs=list(body.get("cited_refs") or []),
        confidence=body.get("confidence") or "low",
        model=body.get("model") or {},
        degraded=bool(body.get("degraded", False)),
        degraded_reason=body.get("degraded_reason") or "",
        simulated=bool(body.get("simulated", False)),
    )


class NarrativeRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, tenant_id: UUID, chain_id: UUID) -> Narrative | None:
        stmt = select(NarrativeRow).where(
            NarrativeRow.tenant_id == tenant_id, NarrativeRow.chain_id == chain_id
        )
        async with self._db.session() as s:
            row = (await s.execute(stmt)).scalar_one_or_none()
        return _narrative_out(row) if row is not None else None

    async def upsert(
        self, tenant_id: UUID, chain_id: UUID, *, subject_type: str, subject_id: str,
        body: NarrativeBody, generated_at: datetime,
    ) -> Narrative:
        stmt = select(NarrativeRow).where(
            NarrativeRow.tenant_id == tenant_id, NarrativeRow.chain_id == chain_id
        )
        async with self._db.transaction() as s:
            row = (await s.execute(stmt)).scalar_one_or_none()
            if row is None:
                row = NarrativeRow(
                    tenant_id=tenant_id, chain_id=chain_id, subject_type=subject_type,
                    subject_id=subject_id, generated_at=generated_at, body=body.as_dict(),
                )
                s.add(row)
            else:
                row.subject_type = subject_type
                row.subject_id = subject_id
                row.generated_at = generated_at
                row.body = body.as_dict()
            await s.flush()
            await s.refresh(row)
        return _narrative_out(row)
