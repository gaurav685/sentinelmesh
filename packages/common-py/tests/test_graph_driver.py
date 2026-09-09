from __future__ import annotations

from typing import Any

import pytest
from neo4j import Query
from neo4j.exceptions import ClientError, ServiceUnavailable

from sm_common.config import AppSettings
from sm_common.graph import Graph, GraphUnavailableError, split_statements


def _settings(**over: Any) -> AppSettings:
    env = {
        "service_name": "graph-svc",
        "pg_password": "pw",
        "internal_jwt_signing_key": "k",
        "oidc_client_secret": "s",
    }
    env.update(over)
    return AppSettings(_env_file=None, **env)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# fake async driver
# --------------------------------------------------------------------------- #
class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __aiter__(self) -> _FakeResult:
        return self

    async def __anext__(self) -> Any:
        if not self._rows:
            raise StopAsyncIteration
        row = self._rows.pop(0)
        return type("Rec", (), {"data": lambda self, _r=row: _r})()


class _FakeSession:
    def __init__(self, driver: _FakeDriver, mode: str) -> None:
        self._driver = driver
        self._mode = mode

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def run(self, query: Query, params: dict[str, Any]) -> _FakeResult:
        self._driver.calls.append((query, params, self._mode))
        if self._driver.run_exc is not None:
            raise self._driver.run_exc
        return _FakeResult(list(self._driver.rows))


class _FakeDriver:
    def __init__(
        self,
        *,
        rows: list[dict[str, Any]] | None = None,
        run_exc: Exception | None = None,
        connect_exc: Exception | None = None,
    ) -> None:
        self.rows = rows or []
        self.run_exc = run_exc
        self.connect_exc = connect_exc
        self.calls: list[tuple[Query, dict[str, Any], str]] = []
        self.closed = False

    async def verify_connectivity(self) -> None:
        if self.connect_exc is not None:
            raise self.connect_exc

    def session(self, *, database: str, default_access_mode: str) -> _FakeSession:
        assert database == "neo4j"
        return _FakeSession(self, default_access_mode)

    async def close(self) -> None:
        self.closed = True


def _graph(driver: _FakeDriver, timeout_ms: int = 10_000) -> Graph:
    return Graph(driver, database="neo4j", query_timeout_ms=timeout_ms)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
def test_from_settings_does_not_connect() -> None:
    g = Graph.from_settings(_settings(neo4j_query_timeout_ms="4000"))
    assert g._timeout_s == 4.0  # type: ignore[attr-defined]


def test_zero_timeout_means_no_deadline() -> None:
    assert _graph(_FakeDriver(), timeout_ms=0)._timeout_s is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_run_read_passes_params_timeout_and_mode() -> None:
    drv = _FakeDriver(rows=[{"n": 1}, {"n": 2}])
    async with _graph(drv) as g:
        out = await g.run_read("MATCH (n) RETURN n", {"x": "y"})
    assert out == [{"n": 1}, {"n": 2}]
    query, params, mode = drv.calls[0]
    assert params == {"x": "y"}
    assert mode == "READ"
    assert query.timeout == 10.0


@pytest.mark.asyncio
async def test_run_write_uses_write_mode_and_empty_params_default() -> None:
    drv = _FakeDriver()
    await _graph(drv).run_write("CREATE (n:Host {uid: $uid})")
    _query, params, mode = drv.calls[0]
    assert mode == "WRITE"
    assert params == {}


@pytest.mark.asyncio
async def test_start_wraps_service_unavailable() -> None:
    g = _graph(_FakeDriver(connect_exc=ServiceUnavailable("down")))
    with pytest.raises(GraphUnavailableError):
        await g.start()


@pytest.mark.asyncio
async def test_ping_wraps_service_unavailable() -> None:
    with pytest.raises(GraphUnavailableError):
        await _graph(_FakeDriver(connect_exc=ServiceUnavailable("down"))).ping()


@pytest.mark.asyncio
async def test_run_wraps_service_unavailable() -> None:
    with pytest.raises(GraphUnavailableError):
        await _graph(_FakeDriver(run_exc=ServiceUnavailable("mid-query"))).run_read("RETURN 1")


@pytest.mark.asyncio
async def test_run_propagates_neo4j_error_unwrapped() -> None:
    # A constraint violation is a real answer, not an outage — the caller (the
    # graph-writer) must see it to decide DLQ vs. retry.
    with pytest.raises(ClientError):
        await _graph(_FakeDriver(run_exc=ClientError("bad label"))).run_write("CREATE (x)")


@pytest.mark.asyncio
async def test_close_only_closes_a_started_driver() -> None:
    drv = _FakeDriver()
    g = _graph(drv)
    await g.close()
    assert drv.closed is False
    await g.start()
    await g.close()
    assert drv.closed is True


# --------------------------------------------------------------------------- #
# migration statement splitter
# --------------------------------------------------------------------------- #
def test_split_statements_strips_comments_and_splits_on_semicolon() -> None:
    text = """
    // a comment
    CREATE CONSTRAINT a IF NOT EXISTS FOR (n:Host) REQUIRE n.uid IS UNIQUE;
    // another
    CREATE INDEX b IF NOT EXISTS FOR (n:Host) ON (n.tenant_id);
    """
    stmts = split_statements(text)
    assert len(stmts) == 2
    assert stmts[0].startswith("CREATE CONSTRAINT a")
    assert stmts[1].startswith("CREATE INDEX b")


def test_split_statements_ignores_trailing_whitespace_only_chunk() -> None:
    assert split_statements("RETURN 1;   \n  ") == ["RETURN 1"]
