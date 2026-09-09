"""Threat-intel provider adapters. `SM_TI_PROVIDERS` (comma-separated) selects
which are built; empty (the default) means **no outbound calls**."""

from __future__ import annotations

import httpx
import structlog

from sm_common.config import AppSettings

from ..metrics import TiMetrics
from .base import ProviderResult, RawIndicator, ThreatIntelProvider
from .external import build_abusech, build_otx
from .fixture import FixtureProvider

__all__ = [
    "ProviderResult",
    "RawIndicator",
    "ThreatIntelProvider",
    "build_providers",
]

_log = structlog.get_logger("sm.ti_service.providers")


def build_providers(
    settings: AppSettings, http: httpx.AsyncClient, metrics: TiMetrics
) -> list[ThreatIntelProvider]:
    names = [n.strip().lower() for n in settings.ti_providers.split(",") if n.strip()]
    out: list[ThreatIntelProvider] = []
    for name in names:
        if name == "fixture":
            out.append(FixtureProvider())
        elif name == "abusech":
            out.append(build_abusech(
                http, metrics, timeout_s=settings.ti_http_timeout_s,
                max_retries=settings.ti_http_max_retries,
            ))
        elif name == "otx":
            out.append(build_otx(
                http, metrics, timeout_s=settings.ti_http_timeout_s,
                max_retries=settings.ti_http_max_retries,
            ))
        else:
            _log.warning("unknown_ti_provider", name=name)
    return out
