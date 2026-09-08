"""Repository protocols.

Every method that touches tenant-scoped data takes `tenant_id` as its **first**
argument, and callers pass it from the authenticated `Principal` — never from
request data (Engineering Constitution §6). Defining these as Protocols lets the
route tests substitute in-memory repositories and still exercise the real
routing, authentication, authorization and error handling.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sm_common.db.models import Permission, Role, Tenant, User

__all__ = [
    "RoleRepository",
    "TenantRepository",
    "UserRepository",
]


class TenantRepository(Protocol):
    async def get(self, tenant_id: UUID) -> Tenant | None: ...

    async def get_by_slug(self, slug: str) -> Tenant | None: ...


class UserRepository(Protocol):
    async def get(self, tenant_id: UUID, user_id: UUID) -> User | None: ...

    async def get_by_email(self, tenant_id: UUID, email: str) -> User | None: ...

    async def get_by_external_subject(self, tenant_id: UUID, subject: str) -> User | None: ...

    async def list_page(
        self, tenant_id: UUID, *, cursor: UUID | None, limit: int
    ) -> tuple[list[User], UUID | None]:
        """Returns `(users, next_cursor_id)`. Ordered by `id` (UUIDv7 is
        time-ordered, so this is stable and index-friendly)."""
        ...

    async def create(
        self, tenant_id: UUID, *, email: str, display_name: str, status: str
    ) -> User: ...

    async def bind_external_subject(self, tenant_id: UUID, user_id: UUID, subject: str) -> None: ...

    async def record_login_success(self, tenant_id: UUID, user_id: UUID, at: datetime) -> None: ...

    async def record_login_failure(self, tenant_id: UUID, user_id: UUID) -> int:
        """Increment the consecutive-failure counter. Returns the new count."""
        ...

    async def set_lockout(self, tenant_id: UUID, user_id: UUID, until: datetime) -> None:
        """Lock the account until `until`. Kept separate from the counter so a
        lockout never inflates the count it was triggered by."""
        ...


class RoleRepository(Protocol):
    async def get(self, tenant_id: UUID, role_id: UUID) -> Role | None:
        """A role is visible to a tenant if it is that tenant's role or a system
        role (`tenant_id IS NULL`)."""
        ...

    async def get_by_name(self, tenant_id: UUID, name: str) -> Role | None: ...

    async def list_available(self, tenant_id: UUID) -> list[Role]: ...

    async def role_names_for_user(self, tenant_id: UUID, user_id: UUID) -> list[str]: ...

    async def permissions_for_user(self, tenant_id: UUID, user_id: UUID) -> list[Permission]: ...

    async def grant(
        self, tenant_id: UUID, *, user_id: UUID, role_id: UUID, granted_by: UUID
    ) -> bool:
        """Grants the role. Returns False if the grant already existed."""
        ...
