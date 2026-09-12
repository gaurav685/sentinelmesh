"""Async Neo4j driver wrapper (ADR-007; docs/architecture/data-model.md).

- one `AsyncDriver` per process; `start()` verifies connectivity, `close()` on
  shutdown.
- `run_write` / `run_read` take a Cypher string + a parameter dict — **never**
  interpolate; the driver rejects a label/relationship type as a parameter, so
  callers must allowlist those (`sm_contracts.GRAPH_NODE_LABELS` /
  `GRAPH_REL_TYPES`) before building the query.
- every query carries the configured timeout (`SM_NEO4J_QUERY_TIMEOUT_MS`); a
  slow query raises rather than hanging a request.
- `ping()` backs the readiness probe.
"""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase, Query
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from ..config import AppSettings
from ..observability import Metrics

__all__ = ["Graph", "GraphUnavailableError"]

_log = structlog.get_logger("sm.graph")


class GraphUnavailableError(RuntimeError):
    """Neo4j is unreachable — the caller turns this into a 503 / TransientError."""


class Graph:
    def __init__(
        self,
        driver: AsyncDriver,
        *,
        database: str,
        query_timeout_ms: int,
        metrics: Metrics | None = None,
    ) -> None:
        self._driver = driver
        self._database = database
        self._timeout_s = query_timeout_ms / 1000 if query_timeout_ms > 0 else None
        self._started = False
        self._metrics = metrics

    @classmethod
    def from_settings(cls, settings: AppSettings, *, metrics: Metrics | None = None) -> Graph:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
        )
        return cls(
            driver,
            database=settings.neo4j_database,
            query_timeout_ms=settings.neo4j_query_timeout_ms,
            metrics=metrics,
        )

    async def start(self) -> None:
        if not self._started:
            try:
                await self._driver.verify_connectivity()
            except (ServiceUnavailable, OSError) as exc:
                raise GraphUnavailableError(str(exc)) from exc
            self._started = True

    async def close(self) -> None:
        if self._started:
            await self._driver.close()
            self._started = False

    async def ping(self) -> None:
        try:
            await self._driver.verify_connectivity()
        except (ServiceUnavailable, OSError) as exc:
            raise GraphUnavailableError(str(exc)) from exc

    async def run_write(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return await self._run(cypher, params, write=True)

    async def run_read(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return await self._run(cypher, params, write=False)

    async def _run(
        self, cypher: str, params: dict[str, Any] | None, *, write: bool
    ) -> list[dict[str, Any]]:
        query = Query(cypher, timeout=self._timeout_s)
        mode = "WRITE" if write else "READ"
        start = time.perf_counter()
        try:
            async with self._driver.session(
                database=self._database, default_access_mode=mode
            ) as session:
                result = await session.run(query, params or {})
                return [record.data() async for record in result]
        except (ServiceUnavailable, OSError) as exc:
            raise GraphUnavailableError(str(exc)) from exc
        except Neo4jError:
            raise
        finally:
            if self._metrics is not None:
                self._metrics.observe_neo4j_query(mode, time.perf_counter() - start)

    async def __aenter__(self) -> Graph:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
