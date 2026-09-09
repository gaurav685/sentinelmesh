from __future__ import annotations

import httpx
import pytest
from sm_ti_service.metrics import TiMetrics
from sm_ti_service.providers import build_providers
from sm_ti_service.providers.base import ProviderAdapter, RawIndicator
from sm_ti_service.providers.fixture import FixtureProvider

from sm_common.observability import build_metrics
from sm_contracts import IndicatorType, TiConfidence, TiSourceKind

from .conftest import build_settings


def _metrics() -> TiMetrics:
    return TiMetrics(build_metrics("threat-intel-service"), "threat-intel-service")


async def test_fixture_provider_is_labelled_and_deterministic() -> None:
    p = FixtureProvider()
    assert p.source_kind is TiSourceKind.fixture and p.name == "fixture"
    a = await p.fetch()
    b = await p.fetch()
    assert a.ok and [i.value for i in a.indicators] == [i.value for i in b.indicators]
    assert all(i.expires_at is not None for i in a.indicators)


async def test_build_providers_is_empty_by_default() -> None:
    assert build_providers(build_settings(), httpx.AsyncClient(), _metrics()) == []


async def test_build_providers_selects_by_name() -> None:
    got = build_providers(build_settings(ti_providers="fixture, mystery"), httpx.AsyncClient(), _metrics())
    assert [p.name for p in got] == ["fixture"]  # unknown 'mystery' skipped


def _parse_ok(row: dict) -> RawIndicator:
    return RawIndicator(type=IndicatorType.ipv4, value=row["ip"], confidence=TiConfidence.medium)


async def _fetch_json(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get("https://x/")
    r.raise_for_status()
    return list(r.json())


async def test_adapter_maps_an_outage_to_ok_false() -> None:
    def _handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    adapter = ProviderAdapter(
        name="t", source_kind=TiSourceKind.feed, http=http, fetch=_fetch_json,
        parse=_parse_ok, metrics=_metrics(), timeout_s=1.0, max_retries=0,
    )
    result = await adapter.fetch()
    assert result.ok is False and result.indicators == []


async def test_adapter_drops_malformed_rows_but_keeps_the_good_ones() -> None:
    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"ip": "1.2.3.4"}, {"oops": 1}, {"ip": "5.6.7.8"}])

    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    async def _fetch(client: httpx.AsyncClient) -> list[dict]:
        r = await client.get("https://x/")
        r.raise_for_status()
        return list(r.json())

    def _parse(row: dict) -> RawIndicator:
        return RawIndicator(type=IndicatorType.ipv4, value=row["ip"], confidence=TiConfidence.low)

    adapter = ProviderAdapter(
        name="t", source_kind=TiSourceKind.feed, http=http, fetch=_fetch, parse=_parse,
        metrics=_metrics(), timeout_s=2.0, max_retries=0,
    )
    result = await adapter.fetch()
    assert result.ok is True
    assert [i.value for i in result.indicators] == ["1.2.3.4", "5.6.7.8"]


async def test_adapter_retries_a_429_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429)

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("sm_ti_service.providers.base.asyncio.sleep", _no_sleep)
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    adapter = ProviderAdapter(
        name="t", source_kind=TiSourceKind.api, http=http, fetch=_fetch_json, parse=_parse_ok,
        metrics=_metrics(), timeout_s=1.0, max_retries=1,
    )
    result = await adapter.fetch()
    assert result.ok is False and calls["n"] == 2
