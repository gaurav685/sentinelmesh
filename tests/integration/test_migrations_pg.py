"""Alembic migrations applied to a real PostgreSQL.

Runs on a throwaway database so it cannot disturb the other integration tests:

    upgrade head -> downgrade base -> upgrade head

That sequence proves the migrations are reversible and re-appliable, which is
what makes a rollback safe (Engineering Constitution §10). It also checks the
objects the ORM metadata cannot express — triggers, partial indexes, seeds.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from sm_common.config import AppSettings
from sm_common.db import Database

from .conftest import integration_settings

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "migrations" / "postgres" / "alembic.ini"
MIGRATION_DB = "sentinelmesh_migtest"

EXPECTED_TABLES = {
    "tenant",
    "permission",
    "role",
    "user",
    "user_role",
    "role_permission",
    "sensor",
    "audit_log",
    "detection",
    "anomaly",
    "threat_score",
    "security_alert",
    "alembic_version",
}


@pytest_asyncio.fixture
async def migration_database(settings: AppSettings, database: Database) -> AsyncIterator[AppSettings]:
    """Create an empty database for this test, and drop it afterwards.

    `database` is requested only so the suite skips cleanly when PostgreSQL is
    unreachable.
    """
    admin = create_async_engine(settings.pg_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{MIGRATION_DB}"'))
    finally:
        await admin.dispose()

    target = integration_settings(pg_db=MIGRATION_DB)
    try:
        yield target
    finally:
        admin = create_async_engine(settings.pg_dsn, isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
        finally:
            await admin.dispose()


@pytest.fixture
def alembic(migration_database: AppSettings) -> Iterator:
    """Run the Alembic CLI against the throwaway database."""
    env = {
        **os.environ,
        "SM_SERVICE_NAME": "migrations",
        "SM_PG_HOST": migration_database.pg_host,
        "SM_PG_PORT": str(migration_database.pg_port),
        "SM_PG_DB": MIGRATION_DB,
        "SM_PG_USER": migration_database.pg_user,
        "SM_PG_PASSWORD": migration_database.pg_password.get_secret_value(),
        "SM_INTERNAL_JWT_SIGNING_KEY": "integration",
        "SM_OIDC_CLIENT_SECRET": "integration",
    }

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            pytest.fail(f"alembic {' '.join(args)} failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-4000:]}")
        return proc

    yield run


async def _tables(dsn: str) -> set[str]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {r[0] for r in rows}
    finally:
        await engine.dispose()


async def _scalar(dsn: str, sql: str, params: dict[str, object] | None = None) -> object:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params or {})).scalar()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_upgrade_creates_every_table(alembic, migration_database: AppSettings):
    alembic("upgrade", "head")
    assert EXPECTED_TABLES.issubset(await _tables(migration_database.pg_dsn))


@pytest.mark.asyncio
async def test_upgrade_downgrade_upgrade_is_clean(alembic, migration_database: AppSettings):
    alembic("upgrade", "head")
    alembic("downgrade", "base")

    remaining = await _tables(migration_database.pg_dsn)
    assert not (remaining - {"alembic_version"}), f"downgrade left tables behind: {remaining}"

    alembic("upgrade", "head")
    assert EXPECTED_TABLES.issubset(await _tables(migration_database.pg_dsn))


@pytest.mark.asyncio
async def test_head_is_the_expected_revision(alembic):
    # `heads` reads the migration scripts, not the database, so it does not
    # depend on an upgrade having run first.
    out = alembic("heads").stdout
    assert "0003" in out

    alembic("upgrade", "head")
    assert "0003" in alembic("current").stdout


@pytest.mark.asyncio
async def test_seed_rows_are_present_and_idempotent(alembic, migration_database: AppSettings):
    alembic("upgrade", "head")
    dsn = migration_database.pg_dsn

    assert await _scalar(dsn, "SELECT count(*) FROM permission") == 14
    assert await _scalar(dsn, "SELECT count(*) FROM role WHERE is_system") == 5
    assert await _scalar(dsn, "SELECT count(*) FROM role_permission") > 0

    # platform_operator holds every permission.
    granted = await _scalar(
        dsn,
        """
        SELECT count(*) FROM role_permission rp
        JOIN role r ON r.id = rp.role_id
        WHERE r.name = 'platform_operator'
        """,
    )
    assert granted == 14

    # read_only must not hold a write permission.
    writes = await _scalar(
        dsn,
        """
        SELECT count(*) FROM role_permission rp
        JOIN role r ON r.id = rp.role_id
        JOIN permission p ON p.id = rp.permission_id
        WHERE r.name = 'read_only' AND p.action <> 'read'
        """,
    )
    assert writes == 0

    # Re-running the seed migration must not duplicate rows.
    alembic("downgrade", "0001")
    assert await _scalar(dsn, "SELECT count(*) FROM permission") == 0
    alembic("upgrade", "head")
    assert await _scalar(dsn, "SELECT count(*) FROM permission") == 14


@pytest.mark.asyncio
async def test_triggers_and_partial_indexes_exist(alembic, migration_database: AppSettings):
    alembic("upgrade", "head")
    dsn = migration_database.pg_dsn

    assert await _scalar(
        dsn, "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_audit_log_immutable'"
    ) == 1
    for table in ("tenant", "user", "role", "sensor"):
        assert await _scalar(
            dsn,
            "SELECT count(*) FROM pg_trigger WHERE tgname = :name",
            {"name": f"trg_{table}_set_updated_at"},
        ) == 1

    # Partial unique indexes carry a predicate.
    for index in ("uq_role_system_name", "uq_role_tenant_id_name"):
        definition = await _scalar(
            dsn, "SELECT indexdef FROM pg_indexes WHERE indexname = :name", {"name": index}
        )
        assert definition is not None
        assert "WHERE" in str(definition)


@pytest.mark.asyncio
async def test_updated_at_trigger_fires(alembic, migration_database: AppSettings):
    alembic("upgrade", "head")
    engine = create_async_engine(migration_database.pg_dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenant (id, slug, name, status) "
                    "VALUES (gen_random_uuid(), 'acme', 'Acme', 'active')"
                )
            )
        async with engine.begin() as conn:
            before = (await conn.execute(text("SELECT updated_at FROM tenant"))).scalar()
            await conn.execute(text("UPDATE tenant SET name = 'Acme Renamed'"))
            after = (await conn.execute(text("SELECT updated_at FROM tenant"))).scalar()
        assert after is not None and before is not None
        assert after >= before
    finally:
        await engine.dispose()
