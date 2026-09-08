from __future__ import annotations

from uuid import UUID

from pydantic import EmailStr, Field

from ..common import SmBaseModel
from ..entities import User

__all__ = ["CreateUserRequest", "GrantRoleRequest", "RoleSummary", "UserResponse"]


class CreateUserRequest(SmBaseModel):
    """Invite/create a user inside the caller's tenant.

    `tenant_id` is intentionally absent: the server uses the authenticated
    caller's tenant. Accepting a client-supplied tenant here would be a
    tenant-injection / mass-assignment flaw (Engineering Constitution §5, §6).
    """

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    role_names: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="System or tenant role names to grant on creation (audited).",
    )


class GrantRoleRequest(SmBaseModel):
    role_id: UUID


class RoleSummary(SmBaseModel):
    id: UUID
    name: str
    description: str
    is_system: bool


class UserResponse(User):
    """Response alias for `User` — kept as an explicit type so the API surface is
    named independently of the internal entity."""
