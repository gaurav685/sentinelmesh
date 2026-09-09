"""The `Enricher` protocol and the runner."""

from __future__ import annotations

from typing import Any, Protocol

import structlog

from sm_contracts import CanonicalEventPayload

__all__ = ["Enricher", "run_enrichers"]

_log = structlog.get_logger("sm.normalization.enrich")


class Enricher(Protocol):
    name: str

    async def enrich(self, payload: CanonicalEventPayload) -> dict[str, Any]:
        """Return this provider's contribution, e.g.
        `{"geoip": {"src": {...}, "provider": "maxmind", "as_of": "..."}}`.
        Must not raise for a lookup miss — return `{}`; a raised exception is
        caught by the runner and recorded as a partial enrichment, never fails
        the event (R2: absent/partial when a provider was unavailable)."""
        ...


async def run_enrichers(
    payload: CanonicalEventPayload, enrichers: tuple[Enricher, ...]
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for enricher in enrichers:
        try:
            merged.update(await enricher.enrich(payload))
        except Exception as exc:  # a provider outage must not fail the event
            _log.warning("enricher_failed", provider=enricher.name, error_type=type(exc).__name__)
            merged.setdefault("_errors", {})[enricher.name] = type(exc).__name__
    return merged
