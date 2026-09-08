"""SQL repositories against a real PostgreSQL.

The unit tests use in-memory repositories, so the actual SQL — the tenant
predicate, the soft-delete filter, the permissions join, cursor pagination and
the `RETURNING` on the login-failure counter — is only exercised here.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest

from sm_api_gateway.repositories.sql import (
    SqlRoleRepository,
    SqlTenantRepository,
    SqlUserRepository,
)
from sm_common.clock import utcnow
from sm_common.db import Database
from sm_common.db.models import Permission, Role, RolePermission, Tenant, User, UserRole
from sm_common.ids import uuid7
from sm_contracts.enums import PermissionCode, TenantStatus, UserStatus

pytestmark = pytest.mark.integration


class World:
    """Two tenants, users in each, one system role with two permissions."""

    def __init__(self) -> None:
        self.acme = uuid7()
        self.globex = uuid7()
        self.acme_users: list[UUID] = []
        self.globex_user = uuid7()
        self.role = uuid7()


async def _seed(db: Database, *, acme_user_count: int = 3) -> World:
    w = World()
    async with db.transaction() as session:
        session.add_all(
            [
                Tenant(id=w.acme, slug="acme", name="Acme", status=TenantStatus.active.value, settings={}),
                Tenant(
                    id=w.globex, slug="globex", name="Globex",
                    status=TenantStatus.active.value, settings={},
                ),
            ]
        )
        await session.flush()

        for i in range(acme_user_count):
            uid = uuid7()
            w.acme_users.append(uid)
            session.add(
                User(
                    id=uid, tenant_id=w.acme, email=f"user{i}@acme-corp.com",
                    display_name=f"User {i}", status=UserStatus.active.value,
                    failed_login_count=0,
                )
            )
        session.add(
            User(
                id=w.globex_user, tenant_id=w.globex, email="admin@globex-inc.com",
                display_name="Globex Admin", status=UserStatus.active.value,
                failed_login_count=0,
            )
        )

        session.add(
            Role(id=w.role, tenant_id=None, name="analyst", description="d", is_system=True)
        )
        perms = []
        for code in (PermissionCode.detections_read, PermissionCode.hunt_query):
            resource, action = code.value.split(":", 1)
            pid = uuid7()
            perms.append(pid)
            session.add(
                Permission(
                    id=pid, code=code.value, description=code.value,
                    resource_type=resource, action=action,
                )
            )
        await session.flush()
        for pid in perms:
            session.add(RolePermission(role_id=w.role, permission_id=pid))
        session.add(
            UserRole(
                user_id=w.acme_users[0], role_id=w.role,
                granted_by=w.acme_users[0], granted_at=utcnow(),
            )
        )
    return w


@pytest.mark.asyncio
async def test_tenant_lookup_by_slug(clean: Database):
    w = await _seed(clean)
    async with clean.session() as session:
        repo = SqlTenantRepository(session)
        assert (await repo.get_by_slug("acme")).id == w.acme
        assert await repo.get_by_slug("no-such-tenant") is None


@pytest.mark.asyncio
async def test_user_get_is_tenant_scoped(clean: Database):
    w = await _seed(clean)
    async with clean.session() as session:
        repo = SqlUserRepository(session)
        # correct tenant
        assert (await repo.get(w.acme, w.acme_users[0])) is not None
        # right user id, wrong tenant -> invisible
        assert await repo.get(w.globex, w.acme_users[0]) is None


@pytest.mark.asyncio
async def test_email_lookup_is_tenant_scoped_and_case_insensitive(clean: Database):
    w = await _seed(clean)
    async with clean.session() as session:
        repo = SqlUserRepository(session)
        assert (await repo.get_by_email(w.acme, "USER0@ACME-CORP.COM")) is not None
        assert await repo.get_by_email(w.globex, "user0@acme-corp.com") is None


@pytest.mark.asyncio
async def test_soft_deleted_users_are_invisible(clean: Database):
    w = await _seed(clean)
    async with clean.transaction() as session:
        user = await SqlUserRepository(session).get(w.acme, w.acme_users[0])
        assert user is not None
        user.deleted_at = utcnow()

    async with clean.session() as session:
        repo = SqlUserRepository(session)
        assert await repo.get(w.acme, w.acme_users[0]) is None
        rows, _ = await repo.list_page(w.acme, cursor=None, limit=50)
        assert w.acme_users[0] not in {u.id for u in rows}


@pytest.mark.asyncio
async def test_list_page_only_returns_the_tenants_users(clean: Database):
    w = await _seed(clean)
    async with clean.session() as session:
        rows, cursor = await SqlUserRepository(session).list_page(w.acme, cursor=None, limit=50)
    assert {u.tenant_id for u in rows} == {w.acme}
    assert cursor is None
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_cursor_pagination_walks_every_user_once(clean: Database):
    w = await _seed(clean, acme_user_count=5)
    seen: list[UUID] = []
    cursor: UUID | None = None
    async with clean.session() as session:
        repo = SqlUserRepository(session)
        for _ in range(10):  # generous bound; the loop must finish well inside it
            rows, cursor = await repo.list_page(w.acme, cursor=cursor, limit=2)
            seen.extend(u.id for u in rows)
            if cursor is None:
                break
    assert len(seen) == 5
    assert len(set(seen)) == 5
    assert seen == sorted(seen, key=lambda u: u.int)


@pytest.mark.asyncio
async def test_permissions_for_user_joins_through_roles(clean: Database):
    w = await _seed(clean)
    async with clean.session() as session:
        repo = SqlRoleRepository(session)
        codes = {p.code for p in await repo.permissions_for_user(w.acme, w.acme_users[0])}
        assert codes == {PermissionCode.detections_read.value, PermissionCode.hunt_query.value}
        assert await repo.role_names_for_user(w.acme, w.acme_users[0]) == ["analyst"]

        # a user with no grants has no permissions
        assert await repo.permissions_for_user(w.acme, w.acme_users[1]) == []


@pytest.mark.asyncio
async def test_permissions_are_not_readable_across_tenants(clean: Database):
    w = await _seed(clean)
    async with clean.session() as session:
        repo = SqlRoleRepository(session)
        # the acme user's grants must not surface when scoped to globex
        assert await repo.permissions_for_user(w.globex, w.acme_users[0]) == []
        assert await repo.role_names_for_user(w.globex, w.acme_users[0]) == []


@pytest.mark.asyncio
async def test_system_roles_are_visible_to_every_tenant(clean: Database):
    w = await _seed(clean)
    async with clean.session() as session:
        repo = SqlRoleRepository(session)
        assert (await repo.get(w.acme, w.role)) is not None
        assert (await repo.get(w.globex, w.role)) is not None
        assert {r.name for r in await repo.list_available(w.globex)} == {"analyst"}


@pytest.mark.asyncio
async def test_grant_is_idempotent(clean: Database):
    w = await _seed(clean)
    async with clean.transaction() as session:
        repo = SqlRoleRepository(session)
        first = await repo.grant(
            w.acme, user_id=w.acme_users[1], role_id=w.role, granted_by=w.acme_users[0]
        )
        assert first is True
    async with clean.transaction() as session:
        repo = SqlRoleRepository(session)
        again = await repo.grant(
            w.acme, user_id=w.acme_users[1], role_id=w.role, granted_by=w.acme_users[0]
        )
        assert again is False


@pytest.mark.asyncio
async def test_login_failure_counter_increments_and_locks(clean: Database):
    w = await _seed(clean)
    async with clean.transaction() as session:
        repo = SqlUserRepository(session)
        assert await repo.record_login_failure(w.acme, w.acme_users[0]) == 1
        assert await repo.record_login_failure(w.acme, w.acme_users[0]) == 2
        assert await repo.record_login_failure(w.acme, w.acme_users[0]) == 3
        await repo.set_lockout(w.acme, w.acme_users[0], utcnow() + timedelta(minutes=15))

    async with clean.session() as session:
        user = await SqlUserRepository(session).get(w.acme, w.acme_users[0])
        assert user is not None
        assert user.failed_login_count == 3, "setting the lockout must not inflate the counter"
        assert user.locked_until is not None


@pytest.mark.asyncio
async def test_login_success_resets_the_counter_and_lock(clean: Database):
    w = await _seed(clean)
    async with clean.transaction() as session:
        repo = SqlUserRepository(session)
        await repo.record_login_failure(w.acme, w.acme_users[0])
        await repo.set_lockout(w.acme, w.acme_users[0], utcnow() + timedelta(minutes=15))
    now = utcnow()
    async with clean.transaction() as session:
        await SqlUserRepository(session).record_login_success(w.acme, w.acme_users[0], now)

    async with clean.session() as session:
        user = await SqlUserRepository(session).get(w.acme, w.acme_users[0])
        assert user is not None
        assert user.failed_login_count == 0
        assert user.locked_until is None
        assert user.last_login_at is not None


@pytest.mark.asyncio
async def test_create_lowercases_the_email(clean: Database):
    w = await _seed(clean)
    async with clean.transaction() as session:
        created = await SqlUserRepository(session).create(
            w.acme, email="Mixed@Acme-Corp.com", display_name="Mixed",
            status=UserStatus.invited.value,
        )
        assert created.email == "mixed@acme-corp.com"
