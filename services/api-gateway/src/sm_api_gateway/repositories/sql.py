"""SQLAlchemy repository implementations.

Tenant scoping rule (Engineering Constitution §6): every statement against a
tenant-scoped table carries `WHERE tenant_id = :tenant_id`, taken from the
argument the route supplies from the authenticated `Principal`. There is no code
path here that reads a tenant from request data. Soft-deleted rows
(`deleted_at IS NOT NULL`) are excluded from every read.

All statements are parameterized SQLAlchemy constructs — no string interpolation.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_common.clock import utcnow
from sm_common.db.models import Permission, Role, RolePermission, Tenant, User, UserRole

__all__ = ["SqlRoleRepository", "SqlTenantRepository", "SqlUserRepository"]


class SqlTenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: UUID) -> Tenant | None:
        row: Tenant | None = await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        return row

    async def get_by_slug(self, slug: str) -> Tenant | None:
        row: Tenant | None = await self._session.scalar(
            select(Tenant).where(Tenant.slug == slug)
        )
        return row


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: UUID, user_id: UUID) -> User | None:
        row: User | None = await self._session.scalar(
            select(User).where(
                User.tenant_id == tenant_id, User.id == user_id, User.deleted_at.is_(None)
            )
        )
        return row

    async def get_by_email(self, tenant_id: UUID, email: str) -> User | None:
        row: User | None = await self._session.scalar(
            select(User).where(
                User.tenant_id == tenant_id,
                User.email == email.lower(),
                User.deleted_at.is_(None),
            )
        )
        return row

    async def get_by_external_subject(self, tenant_id: UUID, subject: str) -> User | None:
        row: User | None = await self._session.scalar(
            select(User).where(
                User.tenant_id == tenant_id,
                User.external_subject == subject,
                User.deleted_at.is_(None),
            )
        )
        return row

    async def list_page(
        self, tenant_id: UUID, *, cursor: UUID | None, limit: int
    ) -> tuple[list[User], UUID | None]:
        stmt = select(User).where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
        if cursor is not None:
            stmt = stmt.where(User.id > cursor)
        # Fetch one extra row to learn whether another page exists, without a
        # second COUNT query.
        stmt = stmt.order_by(User.id).limit(limit + 1)
        rows = list((await self._session.scalars(stmt)).all())
        if len(rows) > limit:
            return rows[:limit], rows[limit - 1].id
        return rows, None

    async def create(self, tenant_id: UUID, *, email: str, display_name: str, status: str) -> User:
        user = User(
            tenant_id=tenant_id,
            email=email.lower(),
            display_name=display_name,
            status=status,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def bind_external_subject(self, tenant_id: UUID, user_id: UUID, subject: str) -> None:
        await self._session.execute(
            update(User)
            .where(User.tenant_id == tenant_id, User.id == user_id)
            .values(external_subject=subject)
        )

    async def record_login_success(self, tenant_id: UUID, user_id: UUID, at: datetime) -> None:
        await self._session.execute(
            update(User)
            .where(User.tenant_id == tenant_id, User.id == user_id)
            .values(last_login_at=at, failed_login_count=0, locked_until=None)
        )

    async def record_login_failure(self, tenant_id: UUID, user_id: UUID) -> int:
        # Incremented in SQL, not read-modify-write, so concurrent failed
        # attempts cannot lose a count.
        result = await self._session.execute(
            update(User)
            .where(User.tenant_id == tenant_id, User.id == user_id)
            .values(failed_login_count=User.failed_login_count + 1)
            .returning(User.failed_login_count)
        )
        count = result.scalar_one_or_none()
        return int(count) if count is not None else 0

    async def set_lockout(self, tenant_id: UUID, user_id: UUID, until: datetime) -> None:
        await self._session.execute(
            update(User)
            .where(User.tenant_id == tenant_id, User.id == user_id)
            .values(locked_until=until)
        )


class SqlRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _visible(self, tenant_id: UUID) -> ColumnElement[bool]:
        # A tenant sees its own roles plus the shared system roles.
        return (Role.tenant_id == tenant_id) | (Role.tenant_id.is_(None))

    async def get(self, tenant_id: UUID, role_id: UUID) -> Role | None:
        row: Role | None = await self._session.scalar(
            select(Role).where(Role.id == role_id, self._visible(tenant_id))
        )
        return row

    async def get_by_name(self, tenant_id: UUID, name: str) -> Role | None:
        row: Role | None = await self._session.scalar(
            select(Role).where(Role.name == name, self._visible(tenant_id))
        )
        return row

    async def list_available(self, tenant_id: UUID) -> list[Role]:
        stmt = select(Role).where(self._visible(tenant_id)).order_by(Role.name)
        return list((await self._session.scalars(stmt)).all())

    async def role_names_for_user(self, tenant_id: UUID, user_id: UUID) -> list[str]:
        stmt = (
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(User, User.id == UserRole.user_id)
            .where(User.tenant_id == tenant_id, User.id == user_id, User.deleted_at.is_(None))
            .order_by(Role.name)
        )
        return list((await self._session.scalars(stmt)).all())

    async def permissions_for_user(self, tenant_id: UUID, user_id: UUID) -> list[Permission]:
        # Single join: no N+1 over roles.
        stmt = (
            select(Permission)
            .distinct()
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .join(User, User.id == UserRole.user_id)
            .where(User.tenant_id == tenant_id, User.id == user_id, User.deleted_at.is_(None))
            .order_by(Permission.code)
        )
        return list((await self._session.scalars(stmt)).all())

    async def grant(
        self, tenant_id: UUID, *, user_id: UUID, role_id: UUID, granted_by: UUID
    ) -> bool:
        existing = await self._session.scalar(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
        )
        if existing is not None:
            return False
        self._session.add(
            UserRole(user_id=user_id, role_id=role_id, granted_by=granted_by, granted_at=utcnow())
        )
        await self._session.flush()
        return True
