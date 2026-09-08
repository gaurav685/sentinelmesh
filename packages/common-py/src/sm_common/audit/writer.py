"""Append-only audit writer (Engineering Constitution §5; security-model.md §8).

Each tenant's audit log is a hash chain. `AuditWriter.append` runs inside the
caller's transaction, so for a response-critical action the audit row and the
action commit or roll back together — an action never happens without its audit
record.

Concurrency: two concurrent appends for the same tenant would otherwise read the
same `prev_hash` and fork the chain. A transaction-scoped Postgres advisory lock
keyed on the tenant serializes appends per tenant and is released at commit or
rollback. It does not block other tenants.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..clock import utcnow
from ..db.models import AuditLog
from .hashing import GENESIS_HASH, compute_entry_hash

__all__ = ["PLATFORM_LOCK_KEY", "AuditWriter"]

PLATFORM_LOCK_KEY = "__platform__"
"""Advisory-lock key used for platform-level (tenant_id IS NULL) entries."""


class AuditWriter:
    async def append(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID | None,
        actor_type: str,
        action: str,
        resource_type: str,
        result: str,
        actor_id: UUID | None = None,
        resource_id: str | None = None,
        request_id: UUID | None = None,
        correlation_id: UUID | None = None,
        ip: str | None = None,
        meta: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditLog:
        created_at = occurred_at or utcnow()
        await self._lock_tenant(session, tenant_id)
        prev_hash = await self._last_hash(session, tenant_id)

        payload: dict[str, Any] = {
            "tenant_id": str(tenant_id) if tenant_id else None,
            "actor_type": actor_type,
            "actor_id": str(actor_id) if actor_id else None,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "result": result,
            "request_id": str(request_id) if request_id else None,
            "correlation_id": str(correlation_id) if correlation_id else None,
            "ip": ip,
            "metadata": meta or {},
            "created_at": created_at.isoformat(),
        }
        entry_hash = compute_entry_hash(prev_hash, payload)

        entry = AuditLog(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            request_id=request_id,
            correlation_id=correlation_id,
            ip=ip,
            meta=meta or {},
            created_at=created_at,
            prev_hash=prev_hash,
            hash=entry_hash,
        )
        session.add(entry)
        await session.flush()
        return entry

    @staticmethod
    def hash_payload(entry: AuditLog) -> dict[str, Any]:
        """Rebuild the hashed payload for a stored row, for chain verification."""
        return {
            "tenant_id": str(entry.tenant_id) if entry.tenant_id else None,
            "actor_type": entry.actor_type,
            "actor_id": str(entry.actor_id) if entry.actor_id else None,
            "action": entry.action,
            "resource_type": entry.resource_type,
            "resource_id": entry.resource_id,
            "result": entry.result,
            "request_id": str(entry.request_id) if entry.request_id else None,
            "correlation_id": str(entry.correlation_id) if entry.correlation_id else None,
            "ip": entry.ip,
            "metadata": entry.meta,
            "created_at": entry.created_at.isoformat(),
        }

    async def _lock_tenant(self, session: AsyncSession, tenant_id: UUID | None) -> None:
        key = str(tenant_id) if tenant_id else PLATFORM_LOCK_KEY
        # `hashtextextended` returns bigint (64-bit), so two tenants sharing a
        # lock slot by hash collision is 2^-64, not 2^-32 as with `hashtext`.
        # A collision would only over-serialize; it can never corrupt the chain.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )

    async def _last_hash(self, session: AsyncSession, tenant_id: UUID | None) -> str:
        stmt = select(AuditLog.hash)
        stmt = (
            stmt.where(AuditLog.tenant_id.is_(None))
            if tenant_id is None
            else stmt.where(AuditLog.tenant_id == tenant_id)
        )
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(1)
        result = await session.execute(stmt)
        last = result.scalar_one_or_none()
        return last if last is not None else GENESIS_HASH
