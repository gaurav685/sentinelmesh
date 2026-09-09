"""Deterministic local provider — clearly labelled as a fixture.

`source_kind = FIXTURE` and `provider = "fixture"` propagate into every stored
indicator's provenance, so fixture data can never be mistaken for a real feed
(TB-4). Used for local dev and the integration tests.
"""

from __future__ import annotations

from datetime import timedelta

from sm_common.clock import utcnow
from sm_contracts import IndicatorType, TiConfidence, TiSourceKind

from .base import ProviderResult, RawIndicator

__all__ = ["FixtureProvider"]

_FIXTURES: list[RawIndicator] = [
    RawIndicator(
        type=IndicatorType.ipv4, value="198.51.100.23", confidence=TiConfidence.high,
        tags=["c2", "malware"], reference="fixture://demo/c2-list#1",
    ),
    RawIndicator(
        type=IndicatorType.domain, value="malware-delivery.example", confidence=TiConfidence.medium,
        tags=["phishing"], reference="fixture://demo/phish-list#1",
    ),
    RawIndicator(
        type=IndicatorType.sha256, value="a" * 64, confidence=TiConfidence.high,
        tags=["ransomware"], reference="fixture://demo/hash-list#1",
    ),
]


class FixtureProvider:
    name = "fixture"
    source_kind = TiSourceKind.fixture

    async def fetch(self) -> ProviderResult:
        expires = utcnow() + timedelta(days=7)
        return ProviderResult(
            provider=self.name,
            ok=True,
            indicators=[
                RawIndicator(
                    type=f.type, value=f.value, confidence=f.confidence, tags=list(f.tags),
                    reference=f.reference, actor_id=f.actor_id, expires_at=expires,
                )
                for f in _FIXTURES
            ],
        )
