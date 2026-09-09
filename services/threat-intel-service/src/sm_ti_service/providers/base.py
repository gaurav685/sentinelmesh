"""Provider-adapter architecture (req 9, TB-4).

    ThreatIntelProvider  (what the poller consumes)
      -> ProviderAdapter  (timeout / retry / 429 / malformed / outage handling)
        -> ExternalProvider  (the actual HTTP call + row parser)

TB-4: a provider's response is **untrusted**. The adapter:
- times each attempt (`SM_TI_HTTP_TIMEOUT_S`);
- retries a transient failure with exponential backoff up to
  `SM_TI_HTTP_MAX_RETRIES`; an HTTP 429 is a retry with a longer backoff;
- on a **malformed row** logs it and drops it — it is never ingested;
- on an **outage** (unreachable, all retries exhausted) returns
  `ProviderResult(ok=False, indicators=[])` — the caller keeps serving cache and
  marks freshness `STALE`, and **nothing is fabricated**.

Every `RawIndicator` becomes a stored `ThreatIndicator` with `provenance.provider`
= the adapter name and `provenance.reference` = the row's source reference.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import httpx
import structlog

from sm_contracts import IndicatorType, TiConfidence, TiSourceKind

from ..metrics import TiMetrics

__all__ = [
    "ExternalFetch",
    "ProviderAdapter",
    "ProviderResult",
    "RawIndicator",
    "RowParser",
    "ThreatIntelProvider",
]

_log = structlog.get_logger("sm.ti_service.providers")


@dataclass(frozen=True)
class RawIndicator:
    type: IndicatorType
    value: str  # raw — normalised by the store, which rejects a bad value
    confidence: TiConfidence
    tags: list[str] = field(default_factory=list)
    reference: str = ""
    actor_id: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    ok: bool
    indicators: list[RawIndicator]
    detail: str = ""


@runtime_checkable
class ThreatIntelProvider(Protocol):
    name: str
    source_kind: TiSourceKind

    async def fetch(self) -> ProviderResult: ...


ExternalFetch = Callable[[httpx.AsyncClient], Awaitable[list[dict[str, Any]]]]
RowParser = Callable[[dict[str, Any]], RawIndicator | None]


class ProviderAdapter:
    def __init__(
        self,
        *,
        name: str,
        source_kind: TiSourceKind,
        http: httpx.AsyncClient,
        fetch: ExternalFetch,
        parse: RowParser,
        metrics: TiMetrics,
        timeout_s: float,
        max_retries: int,
    ) -> None:
        self.name = name
        self.source_kind = source_kind
        self._http = http
        self._fetch = fetch
        self._parse = parse
        self._m = metrics
        self._timeout = timeout_s
        self._max_retries = max_retries

    async def fetch(self) -> ProviderResult:
        rows: list[dict[str, Any]] | None = None
        for attempt in range(self._max_retries + 1):
            try:
                rows = await asyncio.wait_for(self._fetch(self._http), timeout=self._timeout)
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < self._max_retries:
                    self._m.provider(self.name, "rate_limited")
                    await asyncio.sleep(min(30.0, 2.0 ** (attempt + 1)))
                    continue
                self._m.provider(self.name, "http_error")
                return ProviderResult(
                    self.name, ok=False, indicators=[],
                    detail=f"http {exc.response.status_code}",
                )
            except (httpx.HTTPError, TimeoutError) as exc:
                if attempt < self._max_retries:
                    self._m.provider(self.name, "retry")
                    await asyncio.sleep(min(15.0, 2.0**attempt))
                    continue
                self._m.provider(self.name, "outage")
                _log.warning("provider_outage", provider=self.name, error=str(exc))
                return ProviderResult(self.name, ok=False, indicators=[], detail="unreachable")

        if rows is None:
            self._m.provider(self.name, "outage")
            return ProviderResult(self.name, ok=False, indicators=[], detail="no response")

        indicators: list[RawIndicator] = []
        malformed = 0
        for row in rows:
            try:
                parsed = self._parse(row)
            except Exception as exc:
                malformed += 1
                _log.info("provider_row_malformed", provider=self.name, error=str(exc))
                continue
            if parsed is not None:
                indicators.append(parsed)
        if malformed:
            self._m.provider(self.name, "malformed_rows")
        self._m.provider(self.name, "ok")
        return ProviderResult(self.name, ok=True, indicators=indicators)
