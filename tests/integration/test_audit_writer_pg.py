"""`AuditWriter` against a real PostgreSQL.

Covers the parts a fake session cannot: the per-tenant advisory lock actually
serializing concurrent appends, the hash chain staying linear under that
concurrency, and the append-only trigger rejecting UPDATE and DELETE.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select, text, update

from sm_common.audit import GENESIS_HASH, AuditWriter, verify_chain
from sm_common.clock import utcnow
from sm_common.db import Database
from sm_common.db.models import AuditLog, Tenant
from sm_common.ids import uuid7
from sm_contracts.enums import ActorType, AuditResult, TenantStatus

pytestmark = pytest.mark.integration


async def _make_tenant(db: Database, slug: str = "acme") -> UUID:
    async with db.transaction() as session:
        tenant = Tenant(
            id=uuid7(), slug=slug, name="Acme", status=TenantStatus.active.value, settings={}
        )
        session.add(tenant)
        await session.flush()
        return tenant.id


async def _append(db: Database, tenant_id: UUID, action: str) -> str:
    writer = AuditWriter()
    async with db.transaction() as session:
        entry = await writer.append(
            session,
            tenant_id=tenant_id,
            actor_type=ActorType.system.value,
            action=action,
            resource_type="test",
            result=AuditResult.success.value,
        )
        return entry.hash


async def _chain(db: Database, tenant_id: UUID) -> list[AuditLog]:
    async with db.session() as session:
        rows = await session.scalars(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at, AuditLog.id)
        )
        return list(rows.all())


@pytest.mark.asyncio
async def test_first_entry_starts_from_genesis(clean: Database):
    tenant_id = await _make_tenant(clean)
    await _append(clean, tenant_id, "first")
    rows = await _chain(clean, tenant_id)
    assert len(rows) == 1
    assert rows[0].prev_hash == GENESIS_HASH


@pytest.mark.asyncio
async def test_sequential_appends_form_a_verifiable_chain(clean: Database):
    tenant_id = await _make_tenant(clean)
    for i in range(6):
        await _append(clean, tenant_id, f"action.{i}")

    rows = await _chain(clean, tenant_id)
    assert len(rows) == 6
    assert verify_chain([(r.hash, AuditWriter.hash_payload(r)) for r in rows]) is True


@pytest.mark.asyncio
async def test_concurrent_appends_do_not_fork_the_chain(clean: Database):
    """Without the advisory lock, concurrent writers would read the same
    `prev_hash` and produce two entries claiming the same predecessor."""
    tenant_id = await _make_tenant(clean)

    await asyncio.gather(*(_append(clean, tenant_id, f"concurrent.{i}") for i in range(10)))

    rows = await _chain(clean, tenant_id)
    assert len(rows) == 10

    prev_hashes = [r.prev_hash for r in rows]
    assert len(set(prev_hashes)) == len(prev_hashes), "a prev_hash was reused: the chain forked"
    assert verify_chain([(r.hash, AuditWriter.hash_payload(r)) for r in rows]) is True


@pytest.mark.asyncio
async def test_tenants_have_independent_chains(clean: Database):
    a = await _make_tenant(clean, "acme")
    b = await _make_tenant(clean, "globex")
    await _append(clean, a, "a1")
    await _append(clean, b, "b1")

    rows_a = await _chain(clean, a)
    rows_b = await _chain(clean, b)
    assert rows_a[0].prev_hash == GENESIS_HASH
    assert rows_b[0].prev_hash == GENESIS_HASH
    assert rows_a[0].hash != rows_b[0].hash


@pytest.mark.asyncio
async def test_update_is_rejected_by_the_append_only_trigger(clean: Database):
    tenant_id = await _make_tenant(clean)
    await _append(clean, tenant_id, "immutable")
    rows = await _chain(clean, tenant_id)

    with pytest.raises(Exception, match="append-only"):
        async with clean.transaction() as session:
            await session.execute(
                update(AuditLog).where(AuditLog.id == rows[0].id).values(action="tampered")
            )


@pytest.mark.asyncio
async def test_delete_is_rejected_by_the_append_only_trigger(clean: Database):
    tenant_id = await _make_tenant(clean)
    await _append(clean, tenant_id, "immutable")

    with pytest.raises(Exception, match="append-only"):
        async with clean.transaction() as session:
            await session.execute(text("DELETE FROM audit_log"))


@pytest.mark.asyncio
async def test_audit_row_rolls_back_with_its_action(clean: Database):
    """An action that fails must not leave an audit row claiming it happened."""
    tenant_id = await _make_tenant(clean)

    with pytest.raises(RuntimeError):
        async with clean.transaction() as session:
            await AuditWriter().append(
                session,
                tenant_id=tenant_id,
                actor_type=ActorType.system.value,
                action="will.fail",
                resource_type="test",
                result=AuditResult.success.value,
                occurred_at=utcnow(),
            )
            raise RuntimeError("the action failed after the audit row was written")

    assert await _chain(clean, tenant_id) == []
