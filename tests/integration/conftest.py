"""Integration-test rig: real PostgreSQL and real Redis.

These tests exercise what unit tests with fakes cannot — constraints, triggers,
transaction and locking behaviour, TTL semantics. They need the compose stack:

    docker compose -f deploy/docker/docker-compose.yml up -d postgres redis

When the services are not reachable every test in this directory is **skipped**,
not failed, so the suite still runs on a machine without Docker. A skip is not a
pass: `docs/IMPLEMENTATION_STATE.md` records which items remain unverified.

Connection settings come from the same `SM_*` variables the services use, with
compose's published ports as defaults (tests run on the host, not inside the
compose network, so `localhost` is correct here).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from sqlalchemy import text

from sm_common.cache import Cache
from sm_common.config import AppSettings
from sm_common.db import Base, Database

pytestmark = pytest.mark.integration

CONNECT_TIMEOUT_S = 3.0

# In CI a skip must not read as a pass: if the services were supposed to be
# there and are not, that is a failure (Engineering Constitution section 3).
REQUIRE_INTEGRATION = os.environ.get("SM_REQUIRE_INTEGRATION") == "1"


def _unavailable(message: str) -> None:
    if REQUIRE_INTEGRATION:
        pytest.fail(f"SM_REQUIRE_INTEGRATION=1 but {message}")
    pytest.skip(message)

# Tables truncated between tests, children first.
_TABLES_IN_TRUNCATE_ORDER = (
    "audit_log",
    "user_role",
    "role_permission",
    "sensor",
    '"user"',
    "role",
    "permission",
    "tenant",
)


def integration_settings(**over: object) -> AppSettings:
    values: dict[str, object] = {
        "service_name": "integration-tests",
        "env": "ci",
        "pg_host": os.environ.get("SM_TEST_PG_HOST", "localhost"),
        "pg_port": int(os.environ.get("SM_TEST_PG_PORT", "5432")),
        "pg_db": os.environ.get("SM_PG_DB", "sentinelmesh"),
        "pg_user": os.environ.get("SM_PG_USER", "sentinelmesh"),
        "pg_password": os.environ.get("SM_PG_PASSWORD", "sentinelmesh"),
        "redis_url": os.environ.get("SM_TEST_REDIS_URL", "redis://localhost:6379/15"),
        "internal_jwt_signing_key": "integration-signing-key-0123456789",
        "oidc_client_secret": "integration",
        "session_idle_seconds": 60,
        "session_absolute_seconds": 300,
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)  # type: ignore[arg-type]


async def _reachable(probe: Callable[[], Awaitable[None]]) -> bool:
    try:
        await asyncio.wait_for(probe(), timeout=CONNECT_TIMEOUT_S)
    except Exception:
        return False
    return True


@pytest.fixture(scope="session")
def settings() -> AppSettings:
    return integration_settings()


@pytest_asyncio.fixture
async def database(settings: AppSettings) -> AsyncIterator[Database]:
    # Function-scoped: an async engine binds its pool to the running event loop,
    # and pytest-asyncio gives each test its own loop. A session-scoped engine
    # reused across tests raises "attached to a different loop".
    db = Database.from_settings(settings)
    if not await _reachable(db.ping):
        await db.dispose()
        _unavailable(
            "PostgreSQL is not reachable; start it with "
            "`docker compose -f deploy/docker/docker-compose.yml up -d postgres`"
        )
    try:
        yield db
    finally:
        await db.dispose()


@pytest_asyncio.fixture
async def cache(settings: AppSettings) -> AsyncIterator[Cache]:
    # Function-scoped for the same reason as `database`: the redis client is
    # bound to the event loop it was created on.
    c = Cache.from_settings(settings)
    if not await _reachable(c.ping):
        await c.close()
        _unavailable(
            "Redis is not reachable; start it with "
            "`docker compose -f deploy/docker/docker-compose.yml up -d redis`"
        )
    try:
        yield c
    finally:
        # The test database index is disposable.
        await c.client.flushdb()
        await c.close()


@pytest_asyncio.fixture
async def schema(database: Database) -> AsyncIterator[None]:
    """Create the schema directly from the models.

    Migration *content* is verified separately by `test_migrations_pg.py`, which
    runs Alembic against its own database. Building the schema from metadata here
    keeps the other tests independent of migration ordering.
    """
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # Triggers live in the migration, not the metadata; recreate the one the
        # audit tests rely on.
        await conn.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION sm_audit_log_immutable() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        await conn.execute(text("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log"))
        await conn.execute(
            text(
                """
                CREATE TRIGGER trg_audit_log_immutable
                BEFORE UPDATE OR DELETE ON audit_log
                FOR EACH ROW EXECUTE FUNCTION sm_audit_log_immutable();
                """
            )
        )
    yield
    async with database.engine.begin() as conn:
        await conn.execute(text("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log"))
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def clean(database: Database, schema: None) -> AsyncIterator[Database]:
    """Empty tables before each test, keeping the schema."""
    async with database.engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_TABLES_IN_TRUNCATE_ORDER)} RESTART IDENTITY CASCADE")
        )
    yield database
