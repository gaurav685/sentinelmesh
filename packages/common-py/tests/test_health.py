from __future__ import annotations

import pytest

from sm_common.observability import DependencyCheck, evaluate_readiness, liveness


def test_liveness():
    h = liveness("api-gateway", "0.1.0")
    assert h.status == "ok"
    assert h.service == "api-gateway"


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise ConnectionError("down")


async def _slow() -> None:
    import asyncio

    await asyncio.sleep(1.0)


@pytest.mark.asyncio
async def test_readiness_all_ok():
    r = await evaluate_readiness([DependencyCheck("pg", _ok), DependencyCheck("redis", _ok)])
    assert r.ready is True
    assert all(d.healthy for d in r.dependencies)


@pytest.mark.asyncio
async def test_readiness_required_failure():
    r = await evaluate_readiness([DependencyCheck("pg", _fail)])
    assert r.ready is False
    assert r.dependencies[0].detail == "ConnectionError"


@pytest.mark.asyncio
async def test_readiness_optional_failure_still_ready():
    r = await evaluate_readiness(
        [DependencyCheck("pg", _ok), DependencyCheck("geoip", _fail, required=False)]
    )
    assert r.ready is True


@pytest.mark.asyncio
async def test_readiness_timeout():
    r = await evaluate_readiness([DependencyCheck("slow", _slow, timeout_s=0.05)])
    assert r.ready is False
    assert r.dependencies[0].detail == "timeout"


@pytest.mark.asyncio
async def test_readiness_no_checks():
    r = await evaluate_readiness([])
    assert r.ready is True
