"""In-memory test rig for the API gateway.

The real app is built — real routing, real middleware, real authentication,
real `require_permission`, real exception handlers. Only the infrastructure
collaborators (Postgres, Redis) are replaced with in-memory fakes, so these tests
run without Docker.

Tests that need genuine SQL behaviour (constraints, the audit advisory lock,
migrations) are integration tests and arrive with docker-compose in Unit 5.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from sm_api_gateway.app import create_app
from sm_api_gateway.deps import Services
from sm_api_gateway.security.session import OidcFlowState, SessionRecord
from sm_common.audit import AuditWriter
from sm_common.clock import utcnow
from sm_common.config import AppSettings
from sm_common.db.models import Permission, Role, Tenant, User
from sm_common.ids import uuid7
from sm_common.observability import build_metrics
from sm_common.security import hash_password
from sm_contracts.enums import PermissionCode, TenantStatus, UserStatus

PASSWORD = "correct-horse-battery-staple"


# --------------------------------------------------------------------------- #
# fake infrastructure
# --------------------------------------------------------------------------- #
class FakeSession:
    """Stands in for an AsyncSession. The in-memory repositories ignore it."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


class FakeDatabase:
    def __init__(self) -> None:
        self.healthy = True

    @asynccontextmanager
    async def session(self) -> AsyncIterator[FakeSession]:
        yield FakeSession()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[FakeSession]:
        yield FakeSession()

    async def ping(self) -> None:
        if not self.healthy:
            raise ConnectionError("postgres down")

    async def dispose(self) -> None:
        return None


class FakeRedis:
    """Just enough of redis.asyncio for the rate limiter and readiness."""

    def __init__(self) -> None:
        self.healthy = True
        self._counts: dict[str, int] = {}

    async def ping(self) -> None:
        if not self.healthy:
            raise ConnectionError("redis down")

    async def incr(self, key: str) -> int:
        if not self.healthy:
            raise ConnectionError("redis down")
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True


class FakeCache:
    def __init__(self) -> None:
        self.client = FakeRedis()

    @property
    def healthy(self) -> bool:
        return self.client.healthy

    @healthy.setter
    def healthy(self, value: bool) -> None:
        self.client.healthy = value

    async def ping(self) -> None:
        await self.client.ping()

    async def close(self) -> None:
        return None


class FakeSessionStore:
    def __init__(self, *, absolute_seconds: int = 43_200) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._absolute = absolute_seconds
        self.counter = 0

    async def create(self, *, user_id: UUID, tenant_id: UUID) -> SessionRecord:
        self.counter += 1
        now = utcnow()
        record = SessionRecord(
            session_id=f"sid-{self.counter}",
            user_id=user_id,
            tenant_id=tenant_id,
            csrf_token=f"csrf-{self.counter}",
            created_at=now,
            absolute_expires_at=now + timedelta(seconds=self._absolute),
        )
        self._records[record.session_id] = record
        return record

    async def get(self, session_id: str) -> SessionRecord | None:
        record = self._records.get(session_id)
        if record is None:
            return None
        if utcnow() >= record.absolute_expires_at:
            del self._records[session_id]
            return None
        return record

    async def delete(self, session_id: str) -> None:
        self._records.pop(session_id, None)


class FakeOidcStateStore:
    def __init__(self) -> None:
        self._states: dict[str, OidcFlowState] = {}

    async def create(
        self, *, tenant_id: UUID, nonce: str, code_verifier: str, redirect_uri: str
    ) -> OidcFlowState:
        flow = OidcFlowState(
            state=f"state-{len(self._states) + 1}",
            tenant_id=tenant_id,
            nonce=nonce,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        self._states[flow.state] = flow
        return flow

    async def consume(self, state: str) -> OidcFlowState | None:
        return self._states.pop(state, None)


class RecordingAuditWriter(AuditWriter):
    """Captures audit calls instead of writing rows."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.fail = False

    async def append(self, session: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        if self.fail:
            raise ConnectionError("audit store unavailable")
        self.entries.append(kwargs)
        return None

    def actions(self) -> list[str]:
        return [e["action"] for e in self.entries]

    def last(self) -> dict[str, Any]:
        return self.entries[-1]


# --------------------------------------------------------------------------- #
# in-memory repositories
# --------------------------------------------------------------------------- #
@dataclass
class Store:
    tenants: dict[UUID, Tenant] = field(default_factory=dict)
    users: dict[UUID, User] = field(default_factory=dict)
    roles: dict[UUID, Role] = field(default_factory=dict)
    permissions: dict[UUID, Permission] = field(default_factory=dict)
    role_permissions: set[tuple[UUID, UUID]] = field(default_factory=set)
    user_roles: set[tuple[UUID, UUID]] = field(default_factory=set)


class InMemoryTenantRepo:
    def __init__(self, store: Store) -> None:
        self._s = store

    async def get(self, tenant_id: UUID) -> Tenant | None:
        return self._s.tenants.get(tenant_id)

    async def get_by_slug(self, slug: str) -> Tenant | None:
        return next((t for t in self._s.tenants.values() if t.slug == slug), None)


class InMemoryUserRepo:
    def __init__(self, store: Store) -> None:
        self._s = store

    def _alive(self, u: User) -> bool:
        return u.deleted_at is None

    async def get(self, tenant_id: UUID, user_id: UUID) -> User | None:
        u = self._s.users.get(user_id)
        return u if u and u.tenant_id == tenant_id and self._alive(u) else None

    async def get_by_email(self, tenant_id: UUID, email: str) -> User | None:
        return next(
            (
                u
                for u in self._s.users.values()
                if u.tenant_id == tenant_id and u.email == email.lower() and self._alive(u)
            ),
            None,
        )

    async def get_by_external_subject(self, tenant_id: UUID, subject: str) -> User | None:
        return next(
            (
                u
                for u in self._s.users.values()
                if u.tenant_id == tenant_id and u.external_subject == subject and self._alive(u)
            ),
            None,
        )

    async def list_page(
        self, tenant_id: UUID, *, cursor: UUID | None, limit: int
    ) -> tuple[list[User], UUID | None]:
        rows = sorted(
            (u for u in self._s.users.values() if u.tenant_id == tenant_id and self._alive(u)),
            key=lambda u: u.id.int,
        )
        if cursor is not None:
            rows = [u for u in rows if u.id.int > cursor.int]
        if len(rows) > limit:
            return rows[:limit], rows[limit - 1].id
        return rows, None

    async def create(self, tenant_id: UUID, *, email: str, display_name: str, status: str) -> User:
        now = utcnow()
        user = User(
            id=uuid7(),
            tenant_id=tenant_id,
            email=email.lower(),
            display_name=display_name,
            status=status,
            failed_login_count=0,
            created_at=now,
            updated_at=now,
        )
        self._s.users[user.id] = user
        return user

    async def bind_external_subject(self, tenant_id: UUID, user_id: UUID, subject: str) -> None:
        user = await self.get(tenant_id, user_id)
        if user is not None:
            user.external_subject = subject

    async def record_login_success(self, tenant_id: UUID, user_id: UUID, at: datetime) -> None:
        user = await self.get(tenant_id, user_id)
        if user is not None:
            user.last_login_at = at
            user.failed_login_count = 0
            user.locked_until = None

    async def record_login_failure(self, tenant_id: UUID, user_id: UUID) -> int:
        user = await self.get(tenant_id, user_id)
        if user is None:
            return 0
        user.failed_login_count = (user.failed_login_count or 0) + 1
        return user.failed_login_count

    async def set_lockout(self, tenant_id: UUID, user_id: UUID, until: datetime) -> None:
        user = await self.get(tenant_id, user_id)
        if user is not None:
            user.locked_until = until


class InMemoryRoleRepo:
    def __init__(self, store: Store) -> None:
        self._s = store

    def _visible(self, tenant_id: UUID, role: Role) -> bool:
        return role.tenant_id is None or role.tenant_id == tenant_id

    async def get(self, tenant_id: UUID, role_id: UUID) -> Role | None:
        role = self._s.roles.get(role_id)
        return role if role and self._visible(tenant_id, role) else None

    async def get_by_name(self, tenant_id: UUID, name: str) -> Role | None:
        return next(
            (r for r in self._s.roles.values() if r.name == name and self._visible(tenant_id, r)),
            None,
        )

    async def list_available(self, tenant_id: UUID) -> list[Role]:
        return sorted(
            (r for r in self._s.roles.values() if self._visible(tenant_id, r)),
            key=lambda r: r.name,
        )

    async def role_names_for_user(self, tenant_id: UUID, user_id: UUID) -> list[str]:
        user = self._s.users.get(user_id)
        if user is None or user.tenant_id != tenant_id:
            return []
        names = [
            self._s.roles[rid].name for (uid, rid) in self._s.user_roles if uid == user_id
        ]
        return sorted(names)

    async def permissions_for_user(self, tenant_id: UUID, user_id: UUID) -> list[Permission]:
        user = self._s.users.get(user_id)
        if user is None or user.tenant_id != tenant_id:
            return []
        role_ids = {rid for (uid, rid) in self._s.user_roles if uid == user_id}
        perm_ids = {pid for (rid, pid) in self._s.role_permissions if rid in role_ids}
        return sorted(
            (self._s.permissions[pid] for pid in perm_ids), key=lambda p: p.code
        )

    async def grant(
        self, tenant_id: UUID, *, user_id: UUID, role_id: UUID, granted_by: UUID
    ) -> bool:
        key = (user_id, role_id)
        if key in self._s.user_roles:
            return False
        self._s.user_roles.add(key)
        return True


class InMemoryRepositoryFactory:
    def __init__(self, store: Store) -> None:
        self._s = store

    def tenants(self, session: Any) -> InMemoryTenantRepo:
        return InMemoryTenantRepo(self._s)

    def users(self, session: Any) -> InMemoryUserRepo:
        return InMemoryUserRepo(self._s)

    def roles(self, session: Any) -> InMemoryRoleRepo:
        return InMemoryRoleRepo(self._s)


# --------------------------------------------------------------------------- #
# seed data
# --------------------------------------------------------------------------- #
@dataclass
class Fixture:
    store: Store
    services: Services
    audit: RecordingAuditWriter
    sessions: FakeSessionStore
    db: FakeDatabase
    cache: FakeCache
    acme: Tenant
    globex: Tenant
    acme_admin: User
    acme_analyst: User
    globex_admin: User


def _tenant(slug: str, name: str, status: str = TenantStatus.active.value) -> Tenant:
    now = utcnow()
    return Tenant(
        id=uuid7(), slug=slug, name=name, status=status, settings={},
        created_at=now, updated_at=now,
    )


def _user(tenant: Tenant, email: str, *, with_password: bool = True,
          status: str = UserStatus.active.value) -> User:
    now = utcnow()
    return User(
        id=uuid7(),
        tenant_id=tenant.id,
        email=email,
        display_name=email.split("@")[0],
        status=status,
        password_hash=hash_password(PASSWORD) if with_password else None,
        failed_login_count=0,
        created_at=now,
        updated_at=now,
    )


def _role(name: str, description: str) -> Role:
    now = utcnow()
    return Role(
        id=uuid7(), tenant_id=None, name=name, description=description,
        is_system=True, created_at=now, updated_at=now,
    )


def _permission(code: PermissionCode) -> Permission:
    resource, action = code.value.split(":", 1)
    return Permission(
        id=uuid7(), code=code.value, description=code.value,
        resource_type=resource, action=action,
    )


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "api-gateway",
        "pg_password": "x",
        "internal_jwt_signing_key": "k",
        "oidc_client_secret": "s",
        "neo4j_password": "x",
        "session_cookie_secure": False,  # TestClient uses http://
        "login_max_failures": 3,
        "login_lockout_seconds": 300,
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


@pytest.fixture
def fixture() -> Fixture:
    store = Store()

    acme = _tenant("acme", "Acme Corp")
    globex = _tenant("globex", "Globex")
    store.tenants[acme.id] = acme
    store.tenants[globex.id] = globex

    admin_role = _role("tenant_admin", "Tenant administrator")
    analyst_role = _role("analyst", "SOC analyst")
    for r in (admin_role, analyst_role):
        store.roles[r.id] = r

    admin_perms = [
        PermissionCode.users_read,
        PermissionCode.users_create,
        PermissionCode.roles_read,
        PermissionCode.roles_grant,
        PermissionCode.ops_read,
    ]
    analyst_perms = [PermissionCode.detections_read]
    for code in {*admin_perms, *analyst_perms}:
        perm = _permission(code)
        store.permissions[perm.id] = perm

    by_code = {p.code: p for p in store.permissions.values()}
    for code in admin_perms:
        store.role_permissions.add((admin_role.id, by_code[code.value].id))
    for code in analyst_perms:
        store.role_permissions.add((analyst_role.id, by_code[code.value].id))

    acme_admin = _user(acme, "admin@acme-corp.com")
    acme_analyst = _user(acme, "analyst@acme-corp.com")
    globex_admin = _user(globex, "admin@globex-inc.com")
    for u in (acme_admin, acme_analyst, globex_admin):
        store.users[u.id] = u

    store.user_roles.add((acme_admin.id, admin_role.id))
    store.user_roles.add((acme_analyst.id, analyst_role.id))
    store.user_roles.add((globex_admin.id, admin_role.id))

    settings = build_settings()
    db = FakeDatabase()
    cache = FakeCache()
    sessions = FakeSessionStore(absolute_seconds=settings.session_absolute_seconds)
    audit = RecordingAuditWriter()

    services = Services(
        settings=settings,
        db=db,  # type: ignore[arg-type]
        cache=cache,  # type: ignore[arg-type]
        sessions=sessions,
        oidc_states=FakeOidcStateStore(),
        metrics=build_metrics("api-gateway"),
        audit=audit,
        repositories=InMemoryRepositoryFactory(store),  # type: ignore[arg-type]
        http=None,
        oidc=None,
    )

    return Fixture(
        store=store, services=services, audit=audit, sessions=sessions, db=db,
        cache=cache, acme=acme, globex=globex, acme_admin=acme_admin,
        acme_analyst=acme_analyst, globex_admin=globex_admin,
    )


@pytest.fixture
def settings_factory():
    return build_settings


@pytest.fixture
def make_client(fixture: Fixture):
    """Build a TestClient over the real app, optionally with overridden settings."""

    def _make(**settings_over: Any) -> TestClient:
        if settings_over:
            fixture.services.settings = build_settings(**settings_over)
        app = create_app(services=fixture.services)
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        return client

    return _make


@pytest.fixture
def client(fixture: Fixture) -> AsyncIterator[TestClient]:
    app = create_app(services=fixture.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def password() -> str:
    return PASSWORD


@pytest.fixture
def do_login(client: TestClient):
    """POST the local-login endpoint for the shared client."""

    def _login(tenant_slug: str, email: str, password: str = PASSWORD):
        return client.post(
            "/api/v1/auth/login",
            json={"tenant_slug": tenant_slug, "email": email, "password": password},
        )

    return _login


@pytest.fixture
def csrf():
    """Build the CSRF header from a login response."""

    def _headers(response) -> dict[str, str]:
        return {"x-csrf-token": response.headers["x-csrf-token"]}

    return _headers
