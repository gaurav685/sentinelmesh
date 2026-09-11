"""Phase 12 Unit 3 — real PostgreSQL: the decoy registry.

The unit tests use `FakeDecoyRepo`; this exercises the actual SQL — tenant
scoping, idempotent teardown, one-way interaction capture, and the
`network_boundary` `CHECK` that makes `'production'` impossible to record even
outside the API schema.
"""

from __future__ import annotations

import uuid

import pytest
from sm_simulation_service.repository import DecoyRepository
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from sm_common.db import Database
from sm_contracts import DecoyInteractionIn, RegisterDecoyRequest

pytestmark = pytest.mark.integration


async def _tenant(db: Database) -> uuid.UUID:
    tid = uuid.uuid4()
    async with db.transaction() as s:
        await s.execute(
            text("INSERT INTO tenant (id, slug, name, status) VALUES (:id, :slug, 'T', 'active')"),
            {"id": tid, "slug": f"t-{tid.hex[:12]}"},
        )
    return tid


async def test_register_get_and_tenant_isolation(clean: Database) -> None:
    repo = DecoyRepository(clean)
    tenant_a = await _tenant(clean)
    tenant_b = await _tenant(clean)

    decoy = await repo.register(
        tenant_a, RegisterDecoyRequest(name="ssh-honeypot", kind="honeypot_host", network_boundary="isolated")
    )
    assert decoy.status == "active"

    found = await repo.get(tenant_a, uuid.UUID(decoy.id))
    assert found is not None and found.id == decoy.id

    hidden = await repo.get(tenant_b, uuid.UUID(decoy.id))
    assert hidden is None

    listed_a = await repo.list_decoys(tenant_a)
    assert [d.id for d in listed_a] == [decoy.id]
    assert await repo.list_decoys(tenant_b) == []


async def test_teardown_is_idempotent_and_keeps_interaction_history(clean: Database) -> None:
    repo = DecoyRepository(clean)
    tenant = await _tenant(clean)
    decoy = await repo.register(
        tenant, RegisterDecoyRequest(name="ssh-honeypot", kind="honeypot_host", network_boundary="isolated")
    )
    interaction = await repo.record_interaction(
        tenant, uuid.UUID(decoy.id), DecoyInteractionIn(source="10.0.0.9", technique_hint="T1110")
    )
    assert interaction is not None

    first = await repo.teardown(tenant, uuid.UUID(decoy.id))
    assert first is not None and first.status == "torn_down" and first.torn_down_at is not None

    second = await repo.teardown(tenant, uuid.UUID(decoy.id))
    assert second is not None and second.status == "torn_down"
    assert second.torn_down_at == first.torn_down_at

    kept = await repo.list_interactions(tenant, uuid.UUID(decoy.id))
    assert len(kept) == 1


async def test_torn_down_decoy_captures_no_further_interactions(clean: Database) -> None:
    repo = DecoyRepository(clean)
    tenant = await _tenant(clean)
    decoy = await repo.register(
        tenant, RegisterDecoyRequest(name="ssh-honeypot", kind="honeypot_host", network_boundary="isolated")
    )
    await repo.teardown(tenant, uuid.UUID(decoy.id))
    result = await repo.record_interaction(tenant, uuid.UUID(decoy.id), DecoyInteractionIn(source="10.0.0.9"))
    assert result is None


async def test_network_boundary_check_rejects_production_at_the_database_level(clean: Database) -> None:
    tenant = await _tenant(clean)
    with pytest.raises(IntegrityError):
        async with clean.transaction() as s:
            await s.execute(
                text(
                    "INSERT INTO decoy (id, tenant_id, name, kind, network_boundary) "
                    "VALUES (:id, :tenant_id, 'x', 'honeypot_host', 'production')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant},
            )
