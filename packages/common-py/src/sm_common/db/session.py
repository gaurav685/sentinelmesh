"""Session and transaction management (Engineering Constitution §10, §11, §15).

`Database` wraps one `AsyncEngine` and hands out sessions:

- `session()` — a plain session (autobegin, no implicit commit). Use for reads.
- `transaction()` — opens a transaction, commits on success, rolls back on any
  exception. Use for writes. Never leaves a transaction open.

Both are async context managers and always close the session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ..config import AppSettings
from .engine import build_engine

__all__ = ["Database"]


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False, autoflush=False
        )

    @classmethod
    def from_settings(cls, settings: AppSettings, *, echo: bool = False) -> Database:
        return cls(build_engine(settings, echo=echo))

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self._sessionmaker()
        try:
            yield session
        finally:
            await session.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        session = self._sessionmaker()
        try:
            async with session.begin():
                yield session
        finally:
            await session.close()

    async def ping(self) -> None:
        """Raises if the database is unreachable. Used by the readiness check."""
        async with self.session() as session:
            await session.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self._engine.dispose()
