"""Tenant administration routes.

Every route declares a permission; `require_permission` is deny-by-default.
Every write is audited. The tenant is always `principal.tenant_id` — no route
accepts a tenant from the caller, so a `tenant_admin` of one tenant cannot read
or modify another.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sm_common.context import get_correlation_id, get_request_id
from sm_common.errors import Conflict, NotFound, ValidationFailed
from sm_contracts import (
    CreateUserRequest,
    CursorPage,
    GrantRoleRequest,
    RoleSummary,
    UserResponse,
)
from sm_contracts.enums import PermissionCode, UserStatus

from ..deps import Services, get_services, require_permission
from ..mappers import to_role_summary, to_user_response
from ..security.principal import Principal
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/admin", tags=["admin"])

MAX_PAGE_SIZE = 100


def _decode_cursor(cursor: str | None) -> UUID | None:
    if not cursor:
        return None
    try:
        return UUID(cursor)
    except ValueError as exc:
        raise ValidationFailed("cursor is not a valid page token") from exc


@router.get("/users", response_model=CursorPage[UserResponse])
async def list_users(
    cursor: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    principal: Principal = Depends(require_permission(PermissionCode.users_read)),
    services: Services = Depends(get_services),
) -> CursorPage[UserResponse]:
    async with services.db.session() as session:
        rows, next_id = await services.repositories.users(session).list_page(
            principal.tenant_id, cursor=_decode_cursor(cursor), limit=limit
        )
    return CursorPage[UserResponse](
        items=[to_user_response(r) for r in rows],
        next_cursor=str(next_id) if next_id is not None else None,
        limit=limit,
    )


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    principal: Principal = Depends(require_permission(PermissionCode.users_create)),
    services: Services = Depends(get_services),
) -> UserResponse:
    async with services.db.transaction() as session:
        users = services.repositories.users(session)
        roles = services.repositories.roles(session)

        if await users.get_by_email(principal.tenant_id, body.email) is not None:
            raise Conflict("a user with that email already exists in this tenant")

        # Resolve every requested role before creating anything, so a bad role
        # name does not leave a half-provisioned user behind.
        resolved = []
        for name in body.role_names:
            role = await roles.get_by_name(principal.tenant_id, name)
            if role is None:
                raise NotFound(f"role '{name}' is not available to this tenant")
            resolved.append(role)

        user = await users.create(
            principal.tenant_id,
            email=body.email,
            display_name=body.display_name,
            status=UserStatus.invited.value,
        )

        for role in resolved:
            await roles.grant(
                principal.tenant_id,
                user_id=user.id,
                role_id=role.id,
                granted_by=principal.user_id,
            )

        await services.audit.append(
            session,
            tenant_id=principal.tenant_id,
            actor_type="user",
            actor_id=principal.user_id,
            action="admin.user.create",
            resource_type="user",
            resource_id=str(user.id),
            result="success",
            request_id=get_request_id(),
            correlation_id=get_correlation_id(),
            meta={"roles": [r.name for r in resolved]},
        )
        dto = to_user_response(user)

    return dto


@router.get("/roles", response_model=list[RoleSummary])
async def list_roles(
    principal: Principal = Depends(require_permission(PermissionCode.roles_read)),
    services: Services = Depends(get_services),
) -> list[RoleSummary]:
    async with services.db.session() as session:
        rows = await services.repositories.roles(session).list_available(principal.tenant_id)
    return [to_role_summary(r) for r in rows]


@router.post("/users/{user_id}/roles", response_model=RoleSummary, status_code=201)
async def grant_role(
    user_id: UUID,
    body: GrantRoleRequest,
    principal: Principal = Depends(require_permission(PermissionCode.roles_grant)),
    services: Services = Depends(get_services),
) -> RoleSummary:
    async with services.db.transaction() as session:
        users = services.repositories.users(session)
        roles = services.repositories.roles(session)

        target = await users.get(principal.tenant_id, user_id)
        if target is None:
            # Same response as a user in another tenant: no cross-tenant probing.
            raise NotFound("user not found")

        role = await roles.get(principal.tenant_id, body.role_id)
        if role is None:
            raise NotFound("role not found")

        created = await roles.grant(
            principal.tenant_id,
            user_id=target.id,
            role_id=role.id,
            granted_by=principal.user_id,
        )

        await services.audit.append(
            session,
            tenant_id=principal.tenant_id,
            actor_type="user",
            actor_id=principal.user_id,
            action="admin.role.grant",
            resource_type="user_role",
            resource_id=f"{target.id}:{role.id}",
            result="success",
            request_id=get_request_id(),
            correlation_id=get_correlation_id(),
            meta={"role": role.name, "already_granted": not created},
        )
        summary = to_role_summary(role)

    return summary
