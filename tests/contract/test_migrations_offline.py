"""Offline migration checks — no database required.

`alembic upgrade head --sql` compiles the full migration chain to DDL without
connecting, so schema correctness can be checked before Docker exists. Applying
migrations to a real Postgres (and `upgrade/downgrade/upgrade`) is an
`integration` test that needs docker-compose.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "migrations" / "postgres" / "alembic.ini"

EXPECTED_TABLES = (
    "tenant",
    "permission",
    "role",
    "user",
    "user_role",
    "role_permission",
    "sensor",
    "audit_log",
)


@pytest.fixture(scope="module")
def offline_sql() -> str:
    env = {
        **os.environ,
        "SM_SERVICE_NAME": "migrations",
        "SM_PG_PASSWORD": "offline",
        "SM_INTERNAL_JWT_SIGNING_KEY": "offline",
        "SM_OIDC_CLIENT_SECRET": "offline",
    }
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head", "--sql"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"alembic offline run failed:\n{proc.stderr[-3000:]}")
    return proc.stdout


def test_all_tables_created(offline_sql: str):
    for table in EXPECTED_TABLES:
        assert f'CREATE TABLE "{table}"' in offline_sql or f"CREATE TABLE {table}" in offline_sql, table


def test_append_only_audit_trigger_created(offline_sql: str):
    assert "sm_audit_log_immutable" in offline_sql
    assert "trg_audit_log_immutable" in offline_sql


def test_updated_at_trigger_created_for_timestamped_tables(offline_sql: str):
    assert "sm_set_updated_at" in offline_sql
    for table in ("tenant", "user", "role", "sensor"):
        assert f"trg_{table}_set_updated_at" in offline_sql


def test_partial_unique_indexes_on_role(offline_sql: str):
    assert "uq_role_system_name" in offline_sql
    assert "uq_role_tenant_id_name" in offline_sql
    assert "WHERE tenant_id IS NULL" in offline_sql


def test_descending_audit_indexes(offline_sql: str):
    assert "ix_audit_log_tenant_id_created_at ON audit_log (tenant_id, created_at DESC)" in offline_sql


def test_seed_inserts_permissions_and_roles(offline_sql: str):
    assert "INSERT INTO permission" in offline_sql
    assert "INSERT INTO role" in offline_sql
    assert "INSERT INTO role_permission" in offline_sql
    assert "'platform_operator'" in offline_sql
    assert "'hunt:query'" in offline_sql


def test_both_revisions_stamped(offline_sql: str):
    assert "alembic_version" in offline_sql
    assert "'0002'" in offline_sql
