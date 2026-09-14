"""Tenant-scoped decoy + decoy-interaction reads/writes (Phase 12).

Every write and read is scoped to `tenant_id`, always the **caller's**
verified-token tenant, never a request field. Teardown is idempotent (marking
an already torn-down decoy torn-down again is a no-op, not an error) and never
deletes the interaction history — that stays for audit.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from sm_common.clock import utcnow
from sm_common.db import Database
from sm_common.db import DecoyInteractionRow as DecoyInteractionOrm
from sm_common.db import DecoyRow as DecoyOrm
from sm_contracts import Decoy, DecoyInteraction, DecoyInteractionIn, RegisterDecoyRequest

__all__ = ["DecoyRepository"]


def _decoy(r: DecoyOrm) -> Decoy:
    return Decoy(
        id=str(r.id), tenant_id=str(r.tenant_id), name=r.name, kind=r.kind,
        network_boundary=r.network_boundary, status=r.status,
        ttl_seconds=r.ttl_seconds, tags=list(r.tags), created_at=r.created_at,
        torn_down_at=r.torn_down_at,
    )


def _interaction(r: DecoyInteractionOrm) -> DecoyInteraction:
    return DecoyInteraction(
        id=str(r.id), decoy_id=str(r.decoy_id), tenant_id=str(r.tenant_id), source=r.source,
        technique_hint=r.technique_hint, detail=dict(r.detail), captured_at=r.captured_at,
    )


class DecoyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def register(self, tenant_id: UUID, req: RegisterDecoyRequest) -> Decoy:
        row = DecoyOrm(
            tenant_id=tenant_id, name=req.name, kind=req.kind,
            network_boundary=req.network_boundary, ttl_seconds=req.ttl_seconds, tags=req.tags,
        )
        async with self._db.transaction() as s:
            s.add(row)
            await s.flush()
            await s.refresh(row)
        return _decoy(row)

    async def get(self, tenant_id: UUID, decoy_id: UUID) -> Decoy | None:
        async with self._db.session() as s:
            row = (
                await s.execute(
                    select(DecoyOrm).where(DecoyOrm.tenant_id == tenant_id, DecoyOrm.id == decoy_id)
                )
            ).scalar_one_or_none()
        return _decoy(row) if row is not None else None

    async def list_decoys(
        self, tenant_id: UUID, *, status: str | None = None, limit: int = 200
    ) -> list[Decoy]:
        stmt = (
            select(DecoyOrm)
            .where(DecoyOrm.tenant_id == tenant_id)
            .order_by(DecoyOrm.created_at.desc())
            .limit(max(1, min(limit, 1000)))
        )
        if status:
            stmt = stmt.where(DecoyOrm.status == status)
        async with self._db.session() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_decoy(r) for r in rows]

    async def teardown(self, tenant_id: UUID, decoy_id: UUID, *, at: datetime | None = None) -> Decoy | None:
        async with self._db.transaction() as s:
            row = (
                await s.execute(
                    select(DecoyOrm).where(DecoyOrm.tenant_id == tenant_id, DecoyOrm.id == decoy_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.status != "torn_down":
                row.status = "torn_down"
                row.torn_down_at = at or utcnow()
            await s.flush()
            await s.refresh(row)
        return _decoy(row)

    async def record_interaction(
        self, tenant_id: UUID, decoy_id: UUID, interaction: DecoyInteractionIn
    ) -> DecoyInteraction | None:
        """Returns `None` if the decoy does not exist for this tenant, or is
        torn down (a torn-down decoy captures no further interactions)."""
        decoy = await self.get(tenant_id, decoy_id)
        if decoy is None or decoy.status != "active":
            return None
        row = DecoyInteractionOrm(
            decoy_id=decoy_id, tenant_id=tenant_id, source=interaction.source,
            technique_hint=interaction.technique_hint, detail=interaction.detail,
        )
        async with self._db.transaction() as s:
            s.add(row)
            await s.flush()
            await s.refresh(row)
        return _interaction(row)

    async def list_interactions(self, tenant_id: UUID, decoy_id: UUID, *, limit: int = 200) -> list[DecoyInteraction]:
        stmt = (
            select(DecoyInteractionOrm)
            .where(DecoyInteractionOrm.tenant_id == tenant_id, DecoyInteractionOrm.decoy_id == decoy_id)
            .order_by(DecoyInteractionOrm.captured_at.desc())
            .limit(limit)
        )
        async with self._db.session() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_interaction(r) for r in rows]
