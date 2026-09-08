"""Authentication routes.

Local login, the OIDC authorization-code flow (PKCE + state + nonce), logout, and
`/me`.

OIDC does **not** auto-provision unknown people into a tenant. A user must
already exist in the tenant (invited by an admin); the callback binds the IdP
`sub` to that row on first sign-in and matches on `sub` afterwards. An unknown
subject with an unknown email is rejected.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from sm_common.context import get_correlation_id, get_request_id
from sm_common.errors import (
    DependencyUnavailable,
    InvalidCredentials,
    NotFound,
    Unauthenticated,
    ValidationFailed,
)
from sm_common.security import make_pkce, new_state
from sm_contracts import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
)
from sm_contracts.enums import PermissionCode, TenantStatus, UserStatus

from ..deps import Services, get_principal, get_services
from ..mappers import to_tenant, to_user
from ..security.cookies import clear_session_cookies, set_session_cookies
from ..security.login import authenticate_local
from ..security.principal import Principal
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/auth", tags=["auth"])
me_router = APIRouter(prefix=API_PREFIX, tags=["auth"])

OIDC_AUDIT_ACTION = "auth.login.oidc"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    services: Services = Depends(get_services),
) -> LoginResponse:
    settings = services.settings

    # The failure counter and the audit row must persist even though the request
    # fails, so the bookkeeping commits before the generic error is raised.
    async with services.db.transaction() as session:
        outcome = await authenticate_local(
            session,
            tenants=services.repositories.tenants(session),
            users=services.repositories.users(session),
            audit=services.audit,
            tenant_slug=body.tenant_slug,
            email=body.email,
            password=body.password.get_secret_value(),
            max_failures=settings.login_max_failures,
            lockout_seconds=settings.login_lockout_seconds,
            request_id=get_request_id(),
            correlation_id=get_correlation_id(),
            ip=_client_ip(request),
        )

    if not outcome.ok or outcome.user is None:
        services.metrics.authn_failures.labels(settings.service_name, outcome.reason).inc()
        raise InvalidCredentials()

    user = outcome.user
    record = await services.sessions.create(user_id=user.id, tenant_id=user.tenant_id)
    set_session_cookies(response, settings, record)

    async with services.db.session() as session:
        permissions = await services.repositories.roles(session).permissions_for_user(
            user.tenant_id, user.id
        )

    by_value = {c.value: c for c in PermissionCode}
    granted = sorted({p.code for p in permissions})
    return LoginResponse(
        user=to_user(user),
        permissions=[by_value[code] for code in granted if code in by_value],
        session_expires_at=record.absolute_expires_at,
    )


@router.get("/oidc/login")
async def oidc_login(
    tenant: str,
    request: Request,
    services: Services = Depends(get_services),
) -> RedirectResponse:
    if services.oidc is None:
        raise DependencyUnavailable("OIDC is not configured")
    if not tenant:
        raise ValidationFailed("tenant is required")

    async with services.db.session() as session:
        tenant_row = await services.repositories.tenants(session).get_by_slug(tenant)
    if tenant_row is None or tenant_row.status != TenantStatus.active.value:
        # Do not distinguish "no such tenant" from "suspended".
        raise NotFound("tenant not found")

    pkce = make_pkce()
    nonce = new_state()
    redirect_uri = str(request.url_for("oidc_callback"))
    flow = await services.oidc_states.create(
        tenant_id=tenant_row.id,
        nonce=nonce,
        code_verifier=pkce.verifier,
        redirect_uri=redirect_uri,
    )
    url = await services.oidc.authorization_url(
        redirect_uri=redirect_uri, state=flow.state, nonce=nonce, pkce=pkce
    )
    return RedirectResponse(url, status_code=302)


@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(
    request: Request,
    services: Services = Depends(get_services),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = services.settings
    if services.oidc is None:
        raise DependencyUnavailable("OIDC is not configured")
    if error:
        # The provider rejected the request; never echo its text back.
        services.metrics.authn_failures.labels(settings.service_name, "oidc_provider_error").inc()
        raise Unauthenticated("sign-in was not completed")
    if not code or not state:
        raise ValidationFailed("code and state are required")

    flow = await services.oidc_states.consume(state)
    if flow is None:
        services.metrics.authn_failures.labels(settings.service_name, "oidc_bad_state").inc()
        raise Unauthenticated("sign-in state is invalid or expired")

    tokens = await services.oidc.exchange_code(
        code=code, redirect_uri=flow.redirect_uri, code_verifier=flow.code_verifier
    )
    identity = await services.oidc.verify_id_token(tokens.id_token, expected_nonce=flow.nonce)

    async with services.db.transaction() as session:
        users = services.repositories.users(session)
        user = await users.get_by_external_subject(flow.tenant_id, identity.subject)
        if user is None and identity.email:
            candidate = await users.get_by_email(flow.tenant_id, identity.email)
            if candidate is not None:
                await users.bind_external_subject(flow.tenant_id, candidate.id, identity.subject)
                user = candidate

        if user is None or user.status not in (
            UserStatus.active.value,
            UserStatus.invited.value,
        ):
            await services.audit.append(
                session,
                tenant_id=flow.tenant_id,
                actor_type="user",
                actor_id=None,
                action=OIDC_AUDIT_ACTION,
                resource_type="user",
                resource_id=identity.email or identity.subject,
                result="failure",
                ip=_client_ip(request),
                meta={"reason": "no_provisioned_user"},
            )
            services.metrics.authn_failures.labels(
                settings.service_name, "oidc_no_provisioned_user"
            ).inc()
            raise Unauthenticated("this account is not provisioned for that tenant")

        await services.audit.append(
            session,
            tenant_id=flow.tenant_id,
            actor_type="user",
            actor_id=user.id,
            action=OIDC_AUDIT_ACTION,
            resource_type="user",
            resource_id=str(user.id),
            result="success",
            ip=_client_ip(request),
            meta={"reason": "ok"},
        )

    record = await services.sessions.create(user_id=user.id, tenant_id=user.tenant_id)
    target = f"/?{urlencode({'signed_in': '1'})}"
    redirect = RedirectResponse(target, status_code=302)
    set_session_cookies(redirect, settings, record)
    return redirect


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    response: Response,
    principal: Principal = Depends(get_principal),
    services: Services = Depends(get_services),
) -> LogoutResponse:
    await services.sessions.delete(principal.session_id)
    clear_session_cookies(response, services.settings)
    async with services.db.transaction() as session:
        await services.audit.append(
            session,
            tenant_id=principal.tenant_id,
            actor_type="user",
            actor_id=principal.user_id,
            action="auth.logout",
            resource_type="session",
            resource_id=None,
            result="success",
        )
    return LogoutResponse(ok=True)


@me_router.get("/me", response_model=MeResponse)
async def me(
    principal: Principal = Depends(get_principal),
    services: Services = Depends(get_services),
) -> MeResponse:
    async with services.db.session() as session:
        tenant_row = await services.repositories.tenants(session).get(principal.tenant_id)
        user_row = await services.repositories.users(session).get(
            principal.tenant_id, principal.user_id
        )
    if tenant_row is None or user_row is None:
        raise Unauthenticated()
    return MeResponse(
        user=to_user(user_row),
        tenant=to_tenant(tenant_row),
        roles=sorted(principal.roles),
        permissions=principal.permission_codes(),
    )
