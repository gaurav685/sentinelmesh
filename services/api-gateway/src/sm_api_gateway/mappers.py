"""ORM model -> contract DTO mapping.

The only place database rows become API responses. Explicit field-by-field
mapping is deliberate: a new column on a model never leaks into an API response
by accident (Engineering Constitution §8).
"""

from __future__ import annotations

from sm_common.db.models import Role as RoleModel
from sm_common.db.models import Tenant as TenantModel
from sm_common.db.models import User as UserModel
from sm_contracts import RoleSummary, Tenant, User, UserResponse
from sm_contracts.enums import TenantStatus, UserStatus

__all__ = ["to_role_summary", "to_tenant", "to_user", "to_user_response"]


def to_tenant(row: TenantModel) -> Tenant:
    return Tenant(
        id=row.id,
        slug=row.slug,
        name=row.name,
        status=TenantStatus(row.status),
        settings=row.settings,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_user(row: UserModel) -> User:
    return User(
        id=row.id,
        tenant_id=row.tenant_id,
        email=row.email,
        display_name=row.display_name,
        status=UserStatus(row.status),
        external_subject=row.external_subject,
        last_login_at=row.last_login_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_user_response(row: UserModel) -> UserResponse:
    """`UserResponse` is the named API surface for `User`; build it directly
    rather than round-tripping through a dump."""
    return UserResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        email=row.email,
        display_name=row.display_name,
        status=UserStatus(row.status),
        external_subject=row.external_subject,
        last_login_at=row.last_login_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_role_summary(row: RoleModel) -> RoleSummary:
    return RoleSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        is_system=row.is_system,
    )
