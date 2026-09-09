"""External provider adapters — real HTTP shape, feature-flagged **off**.

`SM_TI_PROVIDERS` is empty by default, so neither of these is constructed and no
outbound request is ever made. They are wired through `ProviderAdapter`, which
supplies the timeout / retry / 429 / malformed / outage handling; each one here
provides only the HTTP call and the row parser.

The endpoints and row shapes below match the public formats of abuse.ch (URLhaus
recent CSV-as-JSON export) and AlienVault OTX (subscribed-pulses indicators). No
API key is embedded; production supplies `SM_TI_<PROVIDER>_URL` / `_KEY`.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from sm_contracts import IndicatorType, TiConfidence, TiSourceKind

from ..metrics import TiMetrics
from .base import ProviderAdapter, RawIndicator

__all__ = ["build_abusech", "build_otx"]

_ABUSECH_URL = os.environ.get("SM_TI_ABUSECH_URL", "https://urlhaus-api.abuse.ch/v1/urls/recent/")
_OTX_URL = os.environ.get("SM_TI_OTX_URL", "https://otx.alienvault.com/api/v1/pulses/subscribed")


async def _get_json_list(http: httpx.AsyncClient, url: str, key: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = await http.get(url, headers=headers)
    resp.raise_for_status()
    body = resp.json()
    value = body.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{url} returned a non-list {key!r}")
    return value


def _abusech_parse(row: dict[str, Any]) -> RawIndicator | None:
    url = row["url"]
    tags = [str(t) for t in row.get("tags") or []]
    if row.get("threat"):
        tags.append(str(row["threat"]))
    return RawIndicator(
        type=IndicatorType.url, value=url, confidence=TiConfidence.medium,
        tags=tags, reference=f"urlhaus:{row.get('id', url)}",
    )


def _otx_parse(row: dict[str, Any]) -> RawIndicator | None:
    kind = str(row.get("type", "")).lower()
    mapping = {
        "ipv4": IndicatorType.ipv4, "ipv6": IndicatorType.ipv6, "domain": IndicatorType.domain,
        "hostname": IndicatorType.domain, "url": IndicatorType.url, "filehash-sha256": IndicatorType.sha256,
        "filehash-md5": IndicatorType.md5, "email": IndicatorType.email,
    }
    itype = mapping.get(kind)
    if itype is None:
        return None
    return RawIndicator(
        type=itype, value=str(row["indicator"]), confidence=TiConfidence.medium,
        tags=["otx"], reference=f"otx:{row.get('id', row['indicator'])}",
    )


def build_abusech(
    http: httpx.AsyncClient, metrics: TiMetrics, *, timeout_s: float, max_retries: int,
) -> ProviderAdapter:
    async def fetch(client: httpx.AsyncClient) -> list[dict[str, Any]]:
        return await _get_json_list(client, _ABUSECH_URL, "urls", {"Accept": "application/json"})

    return ProviderAdapter(
        name="abusech", source_kind=TiSourceKind.feed, http=http, fetch=fetch, parse=_abusech_parse,
        metrics=metrics, timeout_s=timeout_s, max_retries=max_retries,
    )


def build_otx(
    http: httpx.AsyncClient, metrics: TiMetrics, *, timeout_s: float, max_retries: int,
) -> ProviderAdapter:
    api_key = os.environ.get("SM_TI_OTX_KEY", "")

    async def fetch(client: httpx.AsyncClient) -> list[dict[str, Any]]:
        pulses = await _get_json_list(client, _OTX_URL, "results", {"X-OTX-API-KEY": api_key})
        rows: list[dict[str, Any]] = []
        for pulse in pulses:
            rows.extend(pulse.get("indicators", []))
        return rows

    return ProviderAdapter(
        name="otx", source_kind=TiSourceKind.api, http=http, fetch=fetch, parse=_otx_parse,
        metrics=metrics, timeout_s=timeout_s, max_retries=max_retries,
    )
