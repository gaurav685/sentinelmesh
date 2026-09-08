"""Schema constraints against a real PostgreSQL.

A constraint that only exists in the model definition protects nothing. These
tests prove the database itself rejects the bad rows.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from sm_common.db import Database
from sm_common.db.models import Permission, Role, Sensor, Tenant, User
from sm_common.ids import uuid7
from sm_contracts.enums import SensorStatus, SensorType, TenantStatus, UserStatus

pytestmark = pytest.mark.integration


def _tenant(slug: str = "acme") -> Tenant:
    return Tenant(
        id=uuid7(), slug=slug, name="Acme", status=TenantStatus.active.value, settings={}
    )


def _user(tenant_id: UUID, email: str) -> User:
    return User(
        id=uuid7(),
        tenant_id=tenant_id,
        email=email,
        display_name="Someone",
        status=UserStatus.active.value,
        failed_login_count=0,
    )


@pytest.mark.asyncio
async def test_tenant_slug_format_is_enforced(clean: Database):
    for bad in ("Acme", "a", "-acme", "acme-", "acme_corp"):
        with pytest.raises((IntegrityError, DBAPIError)):
            async with clean.transaction() as session:
                session.add(_tenant(bad))


@pytest.mark.asyncio
async def test_tenant_slug_is_unique(clean: Database):
    async with clean.transaction() as session:
        session.add(_tenant("acme"))
    with pytest.raises(IntegrityError):
        async with clean.transaction() as session:
            session.add(_tenant("acme"))


@pytest.mark.asyncio
async def test_email_must_be_lowercase(clean: Database):
    async with clean.transaction() as session:
        tenant = _tenant()
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id

    with pytest.raises((IntegrityError, DBAPIError)):
        async with clean.transaction() as session:
            session.add(_user(tenant_id, "Mixed@Case.com"))


@pytest.mark.asyncio
async def test_email_is_unique_per_tenant_but_not_globally(clean: Database):
    async with clean.transaction() as session:
        a, b = _tenant("acme"), _tenant("globex")
        session.add_all([a, b])
        await session.flush()
        a_id, b_id = a.id, b.id

    async with clean.transaction() as session:
        session.add(_user(a_id, "same@example.com"))

    # Same address in a different tenant is fine.
    async with clean.transaction() as session:
        session.add(_user(b_id, "same@example.com"))

    # Same address in the same tenant is not.
    with pytest.raises(IntegrityError):
        async with clean.transaction() as session:
            session.add(_user(a_id, "same@example.com"))


@pytest.mark.asyncio
async def test_failed_login_count_cannot_be_negative(clean: Database):
    async with clean.transaction() as session:
        tenant = _tenant()
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id

    with pytest.raises((IntegrityError, DBAPIError)):
        async with clean.transaction() as session:
            user = _user(tenant_id, "neg@example.com")
            user.failed_login_count = -1
            session.add(user)


@pytest.mark.asyncio
async def test_user_status_must_be_a_known_value(clean: Database):
    async with clean.transaction() as session:
        tenant = _tenant()
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id

    with pytest.raises((IntegrityError, DBAPIError)):
        async with clean.transaction() as session:
            user = _user(tenant_id, "bad@example.com")
            user.status = "not-a-status"
            session.add(user)


@pytest.mark.asyncio
async def test_system_role_name_is_globally_unique(clean: Database):
    async with clean.transaction() as session:
        session.add(
            Role(id=uuid7(), tenant_id=None, name="analyst", description="d", is_system=True)
        )
    with pytest.raises(IntegrityError):
        async with clean.transaction() as session:
            session.add(
                Role(id=uuid7(), tenant_id=None, name="analyst", description="d", is_system=True)
            )


@pytest.mark.asyncio
async def test_tenant_role_name_is_unique_within_a_tenant_only(clean: Database):
    async with clean.transaction() as session:
        a, b = _tenant("acme"), _tenant("globex")
        session.add_all([a, b])
        await session.flush()
        a_id, b_id = a.id, b.id

    async with clean.transaction() as session:
        session.add(Role(id=uuid7(), tenant_id=a_id, name="custom", description="d", is_system=False))
    async with clean.transaction() as session:
        session.add(Role(id=uuid7(), tenant_id=b_id, name="custom", description="d", is_system=False))
    with pytest.raises(IntegrityError):
        async with clean.transaction() as session:
            session.add(
                Role(id=uuid7(), tenant_id=a_id, name="custom", description="d", is_system=False)
            )


@pytest.mark.asyncio
async def test_system_role_must_not_carry_a_tenant(clean: Database):
    async with clean.transaction() as session:
        tenant = _tenant()
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id

    with pytest.raises((IntegrityError, DBAPIError)):
        async with clean.transaction() as session:
            session.add(
                Role(id=uuid7(), tenant_id=tenant_id, name="bad", description="d", is_system=True)
            )


@pytest.mark.asyncio
async def test_permission_code_must_be_a_known_value(clean: Database):
    with pytest.raises((IntegrityError, DBAPIError)):
        async with clean.transaction() as session:
            session.add(
                Permission(
                    id=uuid7(),
                    code="not:a:real:permission",
                    description="d",
                    resource_type="x",
                    action="y",
                )
            )


@pytest.mark.asyncio
async def test_sensor_name_is_unique_per_tenant(clean: Database):
    async with clean.transaction() as session:
        tenant = _tenant()
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id

    def sensor() -> Sensor:
        return Sensor(
            id=uuid7(),
            tenant_id=tenant_id,
            name="edge-01",
            type=SensorType.network.value,
            status=SensorStatus.active.value,
            credential_hash="argon2-placeholder",
        )

    async with clean.transaction() as session:
        session.add(sensor())
    with pytest.raises(IntegrityError):
        async with clean.transaction() as session:
            session.add(sensor())


@pytest.mark.asyncio
async def test_user_requires_an_existing_tenant(clean: Database):
    with pytest.raises(IntegrityError):
        async with clean.transaction() as session:
            session.add(_user(uuid7(), "orphan@example.com"))
