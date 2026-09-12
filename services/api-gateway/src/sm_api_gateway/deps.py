"""Dependency wiring for the API gateway.

`Services` is the single container built once at startup and read from
`app.state`. Everything a route needs is reached through a FastAPI dependency, so
tests can override one collaborator without touching the rest.

`get_principal` is the only place an authenticated identity is produced. It reads
the opaque session cookie, then resolves the user, roles and permissions from the
database on **every request** — nothing about identity or privilege is taken from
the request, and a revoked role takes effect immediately.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_common.audit import AuditWriter
from sm_common.cache import Cache
from sm_common.config import AppSettings
from sm_common.context import get_correlation_id, get_request_id
from sm_common.db import Database
from sm_common.errors import DependencyUnavailable, PermissionDenied, Unauthenticated
from sm_common.observability import Metrics
from sm_common.security import OidcClient
from sm_contracts import ActorType, AuditResult, PermissionCode, UserStatus

from .clients import InternalServiceClient
from .repositories.benchmark import SqlBenchmarkRepository
from .repositories.protocols import (
    BenchmarkRepository,
    RoleRepository,
    SocRepository,
    TenantRepository,
    UserRepository,
)
from .repositories.soc import SqlSocRepository
from .repositories.sql import SqlRoleRepository, SqlTenantRepository, SqlUserRepository
from .security.cookies import CSRF_HEADER
from .security.principal import Principal
from .security.session import OidcStateStore, SessionStore

__all__ = [
    "SAFE_METHODS",
    "RepositoryFactory",
    "Services",
    "SqlRepositoryFactory",
    "get_benchmark_repository",
    "get_internal_client",
    "get_principal",
    "get_services",
    "get_soc_repository",
    "require_permission",
]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_log = structlog.get_logger("sm.api_gateway.authz")


class RepositoryFactory(Protocol):
    def tenants(self, session: AsyncSession) -> TenantRepository: ...

    def users(self, session: AsyncSession) -> UserRepository: ...

    def roles(self, session: AsyncSession) -> RoleRepository: ...


class SqlRepositoryFactory:
    def tenants(self, session: AsyncSession) -> TenantRepository:
        return SqlTenantRepository(session)

    def users(self, session: AsyncSession) -> UserRepository:
        return SqlUserRepository(session)

    def roles(self, session: AsyncSession) -> RoleRepository:
        return SqlRoleRepository(session)


@dataclass
class Services:
    settings: AppSettings
    db: Database
    cache: Cache
    sessions: SessionStore
    oidc_states: OidcStateStore
    metrics: Metrics
    audit: AuditWriter
    repositories: RepositoryFactory
    http: httpx.AsyncClient | None = None
    oidc: OidcClient | None = None
    internal_client: InternalServiceClient | None = None
    soc_repository: SocRepository | None = None
    benchmark_repository: BenchmarkRepository | None = None


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


async def get_read_session(
    services: Services = Depends(get_services),
) -> AsyncIterator[AsyncSession]:
    async with services.db.session() as session:
        yield session


async def get_soc_repository(
    services: Services = Depends(get_services),
) -> AsyncIterator[SocRepository]:
    if services.soc_repository is not None:
        yield services.soc_repository
        return
    async with services.db.session() as session:
        yield SqlSocRepository(session)


async def get_benchmark_repository(
    services: Services = Depends(get_services),
) -> AsyncIterator[BenchmarkRepository]:
    if services.benchmark_repository is not None:
        yield services.benchmark_repository
        return
    async with services.db.session() as session:
        yield SqlBenchmarkRepository(session)


def get_internal_client(services: Services = Depends(get_services)) -> InternalServiceClient:
    if services.internal_client is None:
        raise DependencyUnavailable("internal service client is not configured")
    return services.internal_client


async def get_principal(
    request: Request, services: Services = Depends(get_services)
) -> Principal:
    settings = services.settings
    metrics = services.metrics

    session_id = request.cookies.get(settings.session_cookie_name, "")
    if not session_id:
        metrics.authn_failures.labels(settings.service_name, "no_session_cookie").inc()
        raise Unauthenticated()

    record = await services.sessions.get(session_id)
    if record is None:
        metrics.authn_failures.labels(settings.service_name, "unknown_session").inc()
        raise Unauthenticated()

    # CSRF double-submit on state-changing requests.
    if request.method.upper() not in SAFE_METHODS:
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or supplied != record.csrf_token:
            metrics.authn_failures.labels(settings.service_name, "csrf_mismatch").inc()
            raise PermissionDenied("missing or invalid CSRF token")

    async with services.db.session() as session:
        users = services.repositories.users(session)
        roles = services.repositories.roles(session)

        user = await users.get(record.tenant_id, record.user_id)
        if user is None or user.status != UserStatus.active.value:
            # The session outlived the account; drop it.
            await services.sessions.delete(session_id)
            metrics.authn_failures.labels(settings.service_name, "user_unavailable").inc()
            raise Unauthenticated()

        role_names = await roles.role_names_for_user(record.tenant_id, record.user_id)
        permissions = await roles.permissions_for_user(record.tenant_id, record.user_id)

    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        session_id=record.session_id,
        csrf_token=record.csrf_token,
        roles=frozenset(role_names),
        permissions=frozenset(p.code for p in permissions),
    )


def require_permission(permission: PermissionCode) -> Callable[..., Awaitable[Principal]]:
    """Deny-by-default authorization. A route without one of these is
    unreachable for authenticated callers by convention, and every denial is
    metered and audited."""
    code = permission.value

    async def _dependency(
        principal: Principal = Depends(get_principal),
        services: Services = Depends(get_services),
    ) -> Principal:
        if principal.has(code):
            return principal

        services.metrics.authz_denials.labels(services.settings.service_name, code).inc()

        # The denial itself must not depend on the audit write succeeding. A
        # database outage has to still produce 403, not 500 — turning a refusal
        # into a server error would look like a bug in the caller's request and
        # would hide the denial. The failure is metered and logged instead
        # (failure-model.md, "Audit-write failure").
        try:
            async with services.db.transaction() as session:
                await services.audit.append(
                    session,
                    tenant_id=principal.tenant_id,
                    actor_type=ActorType.user.value,
                    actor_id=principal.user_id,
                    action="authz.denied",
                    resource_type="permission",
                    resource_id=code,
                    result=AuditResult.deny.value,
                    request_id=get_request_id(),
                    correlation_id=get_correlation_id(),
                )
        except Exception:
            services.metrics.audit_write_failures.labels(
                services.settings.service_name, "authz.denied"
            ).inc()
            _log.exception("audit_write_failed", action="authz.denied", permission=code)

        raise PermissionDenied()

    return _dependency
