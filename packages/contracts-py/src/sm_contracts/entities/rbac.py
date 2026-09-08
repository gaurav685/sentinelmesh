from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from ..common import SmBaseModel, TimestampedModel, to_utc
from ..enums import PermissionCode

__all__ = ["Permission", "Role", "RolePermission", "UserRoleGrant"]


class Permission(SmBaseModel):
    """An atomic capability. Seeded and immutable; deny-by-default."""

    id: UUID
    code: PermissionCode
    description: str = Field(min_length=1, max_length=300)
    resource_type: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)


class Role(TimestampedModel):
    """A named bundle of permissions.

    `tenant_id is None` marks a system role (same definition for every tenant).
    A tenant-scoped role has a concrete `tenant_id`.
    """

    id: UUID
    tenant_id: UUID | None = None
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=300)
    is_system: bool


class RolePermission(SmBaseModel):
    role_id: UUID
    permission_id: UUID


class UserRoleGrant(SmBaseModel):
    """A role assignment. Roles are only ever added via this record — there is no
    request field anywhere that can grant a role or permission
    (Engineering Constitution §5, §6: role-escalation prevention)."""

    user_id: UUID
    role_id: UUID
    granted_by: UUID
    granted_at: datetime

    @field_validator("granted_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)
