"""Local-fallback login (Engineering Constitution §5; security-model.md §3).

OIDC is the primary path; this exists for tenants without an IdP and for
break-glass accounts. Properties:

- **No user enumeration.** Every failure returns the same generic error, and the
  caller (the route) raises it only after the bookkeeping transaction commits.
- **No timing oracle.** When the tenant or user does not exist, or the account is
  federated-only, `dummy_verify` burns the same Argon2 work as a real verify.
- **Lockout.** `failed_login_count` accumulates; at the threshold `locked_until`
  is set. A locked account fails generically — the client is not told it is
  locked.
- **Every attempt is audited**, success or failure, with the reason recorded
  server-side only.

`authenticate_local` never raises for a bad credential; it returns a
`LoginOutcome` so the caller can commit the failure counter and the audit row
before responding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from sm_common.audit import AuditWriter
from sm_common.clock import utcnow
from sm_common.db.models import Tenant, User
from sm_common.security import dummy_verify, verify_password
from sm_contracts import ActorType, AuditResult, TenantStatus, UserStatus

from ..repositories.protocols import TenantRepository, UserRepository

__all__ = ["LoginOutcome", "authenticate_local"]

AUDIT_ACTION = "auth.login.local"


@dataclass(frozen=True)
class LoginOutcome:
    ok: bool
    reason: str
    user: User | None = None
    tenant: Tenant | None = None


async def authenticate_local(
    session: AsyncSession,
    *,
    tenants: TenantRepository,
    users: UserRepository,
    audit: AuditWriter,
    tenant_slug: str,
    email: str,
    password: str,
    max_failures: int,
    lockout_seconds: int,
    request_id: UUID | None = None,
    correlation_id: UUID | None = None,
    ip: str | None = None,
) -> LoginOutcome:
    now = utcnow()

    async def record(
        outcome_reason: str,
        *,
        ok: bool,
        tenant_id: UUID | None,
        actor_id: UUID | None,
    ) -> None:
        await audit.append(
            session,
            tenant_id=tenant_id,
            actor_type=ActorType.user.value,
            actor_id=actor_id,
            action=AUDIT_ACTION,
            resource_type="user",
            resource_id=email.lower(),
            result=AuditResult.success.value if ok else AuditResult.failure.value,
            request_id=request_id,
            correlation_id=correlation_id,
            ip=ip,
            meta={"reason": outcome_reason},
        )

    tenant = await tenants.get_by_slug(tenant_slug)
    if tenant is None or tenant.status != TenantStatus.active.value:
        dummy_verify(password)
        await record("unknown_or_inactive_tenant", ok=False, tenant_id=None, actor_id=None)
        return LoginOutcome(ok=False, reason="unknown_or_inactive_tenant")

    user = await users.get_by_email(tenant.id, email)
    if user is None:
        dummy_verify(password)
        await record("unknown_user", ok=False, tenant_id=tenant.id, actor_id=None)
        return LoginOutcome(ok=False, reason="unknown_user")

    if user.locked_until is not None and user.locked_until > now:
        dummy_verify(password)
        await record("account_locked", ok=False, tenant_id=tenant.id, actor_id=user.id)
        return LoginOutcome(ok=False, reason="account_locked")

    if user.status != UserStatus.active.value:
        dummy_verify(password)
        await record("user_not_active", ok=False, tenant_id=tenant.id, actor_id=user.id)
        return LoginOutcome(ok=False, reason="user_not_active")

    if not user.password_hash:
        # Federated-only account: no local password exists to verify.
        dummy_verify(password)
        await record("no_local_password", ok=False, tenant_id=tenant.id, actor_id=user.id)
        return LoginOutcome(ok=False, reason="no_local_password")

    verification = verify_password(user.password_hash, password)
    if not verification.ok:
        count = await users.record_login_failure(tenant.id, user.id, locked_until=None)
        if count >= max_failures:
            await users.record_login_failure(
                tenant.id, user.id, locked_until=now + timedelta(seconds=lockout_seconds)
            )
        await record("bad_password", ok=False, tenant_id=tenant.id, actor_id=user.id)
        return LoginOutcome(ok=False, reason="bad_password")

    await users.record_login_success(tenant.id, user.id, now)
    await record("ok", ok=True, tenant_id=tenant.id, actor_id=user.id)
    return LoginOutcome(ok=True, reason="ok", user=user, tenant=tenant)
