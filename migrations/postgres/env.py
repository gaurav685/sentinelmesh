"""Alembic environment for the SentinelMesh PostgreSQL schema.

The URL comes from the validated `AppSettings`, not from `alembic.ini`, so a
migration run and a service run can never disagree about the target database and
no credential is committed.

Offline mode (`--sql`) emits DDL without connecting — used to review a migration
before it touches a real database.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine

# `AppSettings` requires SM_SERVICE_NAME; migrations are not a service.
os.environ.setdefault("SM_SERVICE_NAME", "migrations")

from sm_common.config import load_settings
from sm_common.db import Base
from sm_common.db.engine import build_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = load_settings()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.pg_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: object) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine: AsyncEngine = build_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
