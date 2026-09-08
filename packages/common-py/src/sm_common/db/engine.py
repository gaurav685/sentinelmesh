"""Async PostgreSQL engine (Engineering Constitution §10, §15).

One `AsyncEngine` per process, built from `AppSettings`. A bounded pool
(`pool_size = SM_PG_POOL_MAX`, no overflow), pre-ping to drop dead connections,
and a per-connection `statement_timeout` so a single slow query cannot pin a
pool slot forever.

`SM_PG_POOL_MIN` is not honored by SQLAlchemy's `QueuePool` (it has no minimum);
it is kept in config for a possible asyncpg-native path and for Neo4j.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ..config import AppSettings

__all__ = ["build_engine"]


def build_engine(settings: AppSettings, *, echo: bool = False) -> AsyncEngine:
    statement_timeout_ms = settings.pg_statement_timeout_ms
    connect_args: dict[str, object] = {}
    if statement_timeout_ms > 0:
        # asyncpg applies this as a session GUC on every pooled connection.
        connect_args["server_settings"] = {"statement_timeout": str(statement_timeout_ms)}

    return create_async_engine(
        settings.pg_dsn,
        echo=echo,
        pool_size=settings.pg_pool_max,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=10,
        connect_args=connect_args,
    )
