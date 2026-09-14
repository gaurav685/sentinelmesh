"""Shared test fixture infrastructure for tests/security, tests/e2e, etc.

Leverages the verified in-memory fixture graph from
services/api-gateway/tests/conftest.py so that security and e2e tests
can drive real routing, auth, authz, RBAC, and error handling hermetically.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sm_api_gateway.app import create_app
from sm_api_gateway.deps import Services
from sm_common.db.models import Role, Tenant, User
from sm_common.security.passwords import hash_password

# Dynamically load the api-gateway conftest module
_gw_conftest_path = Path(__file__).resolve().parent.parent / "services" / "api-gateway" / "tests" / "conftest.py"
_spec = importlib.util.spec_from_file_location("gw_test_conftest", _gw_conftest_path)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Could not load api-gateway conftest from {_gw_conftest_path}")
_gw = importlib.util.module_from_spec(_spec)
sys.modules["gw_test_conftest"] = _gw
_spec.loader.exec_module(_gw)

# Re-export key test doubles and helpers
FakeDatabase = _gw.FakeDatabase
FakeSession = _gw.FakeSession
FakeRedis = _gw.FakeRedis
FakeCache = _gw.FakeCache
FakeSessionStore = _gw.FakeSessionStore
FakeOidcStateStore = _gw.FakeOidcStateStore
RecordingAuditWriter = _gw.RecordingAuditWriter
InMemoryRepositoryFactory = _gw.InMemoryRepositoryFactory
InMemoryTenantRepo = _gw.InMemoryTenantRepo
InMemoryUserRepo = _gw.InMemoryUserRepo
InMemoryRoleRepo = _gw.InMemoryRoleRepo
Store = _gw.Store
build_settings = _gw.build_settings

_PASSWORD = "TestP@ss1!"


@dataclass
class SecurityFixture:
    store: Any
    services: Services
    audit: Any
    sessions: Any
    db: Any
    cache: Any
    acme: Tenant
    globex: Tenant
    acme_admin: User
    acme_analyst: User
    globex_admin: User
    admin_role: Role
    analyst_role: Role


def build_security_fixture(**settings_overrides: Any) -> SecurityFixture:
    # Use unwrap to get raw fixture generator function
    fn = getattr(_gw.fixture, "__wrapped__", _gw.fixture)
    base_fix = fn()
    overrides = {"internal_jwt_signing_key": "k" * 32}
    overrides.update(settings_overrides)
    base_fix.services.settings = _gw.build_settings(**overrides)

    # If settings overrides are passed, rebuild services with them
    if settings_overrides:
        settings = _gw.build_settings(**settings_overrides)
        base_fix.services.settings = settings

    # Ensure passwords match the security test expectation
    for u in (base_fix.acme_admin, base_fix.acme_analyst, base_fix.globex_admin):
        u.password_hash = hash_password(_PASSWORD)

    by_name = {r.name: r for r in base_fix.store.roles.values()}
    admin_role = by_name["tenant_admin"]
    analyst_role = by_name["analyst"]

    return SecurityFixture(
        store=base_fix.store,
        services=base_fix.services,
        audit=base_fix.audit,
        sessions=base_fix.sessions,
        db=base_fix.db,
        cache=base_fix.cache,
        acme=base_fix.acme,
        globex=base_fix.globex,
        acme_admin=base_fix.acme_admin,
        acme_analyst=base_fix.acme_analyst,
        globex_admin=base_fix.globex_admin,
        admin_role=admin_role,
        analyst_role=analyst_role,
    )


@pytest.fixture
def sec_fixture() -> SecurityFixture:
    return build_security_fixture()


@pytest.fixture
def sec_client(sec_fixture: SecurityFixture) -> Iterator[TestClient]:
    app = create_app(services=sec_fixture.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def sec_password() -> str:
    return _PASSWORD


@pytest.fixture
def sec_login(sec_client: TestClient) -> Any:
    def _login(tenant_slug: str, email: str, pw: str = _PASSWORD) -> Any:
        return sec_client.post(
            "/api/v1/auth/login",
            json={"tenant_slug": tenant_slug, "email": email, "password": pw},
        )
    return _login


@pytest.fixture
def sec_csrf() -> Callable[[Any], dict[str, str]]:
    def _headers(response: Any) -> dict[str, str]:
        return {"x-csrf-token": response.headers["x-csrf-token"]}
    return _headers