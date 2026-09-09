"""Threat-intelligence contracts (Phase 6; req 9, TB-4).

Indicators are **never fabricated**. Every `ThreatIndicator` carries a
`provenance` (which source, which reference, when retrieved) and a `source_kind`.
Deterministic local test data is allowed but is labelled `source_kind = FIXTURE`
and `provenance.provider = "fixture:<name>"` — it can never be mistaken for a
real feed.

Freshness is derived, not asserted by a provider: `freshness_for(last_seen,
expires_at, now)` maps age against the source's TTL.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from .common import SmBaseModel, TenantScoped, TimestampedModel, to_utc
from .events import EVENT_PAYLOAD_REGISTRY, EventType

__all__ = [
    "TI_PAYLOADS",
    "EnrichmentMatch",
    "IndicatorFreshness",
    "IndicatorType",
    "Provenance",
    "ThreatActor",
    "ThreatIndicator",
    "TiCampaign",
    "TiConfidence",
    "TiSource",
    "TiSourceKind",
    "TiUpdateAction",
    "TiUpdatePayload",
    "freshness_for",
    "indicator_dedup_key",
    "normalize_indicator_value",
]


class IndicatorType(StrEnum):
    ipv4 = "ipv4"
    ipv6 = "ipv6"
    domain = "domain"
    url = "url"
    sha256 = "sha256"
    sha1 = "sha1"
    md5 = "md5"
    email = "email"


class IndicatorFreshness(StrEnum):
    fresh = "fresh"       # within the source TTL
    aging = "aging"       # past TTL but under 2x
    stale = "stale"       # past 2x TTL, not yet expired
    expired = "expired"   # past expires_at


class TiConfidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class TiSourceKind(StrEnum):
    feed = "feed"          # a downloadable list (abuse.ch, etc.)
    api = "api"            # a queried API (OTX, VT, etc.)
    manual = "manual"      # analyst-submitted
    fixture = "fixture"    # deterministic local test data — never a real feed


class TiUpdateAction(StrEnum):
    added = "added"
    updated = "updated"
    expired = "expired"


_HEX = {IndicatorType.md5: 32, IndicatorType.sha1: 40, IndicatorType.sha256: 64}


def normalize_indicator_value(indicator_type: IndicatorType, raw: str) -> str:
    """Canonical form for de-duplication. Raises `ValueError` on an invalid
    value so the caller can reject a malformed provider row (TB-4)."""
    v = raw.strip()
    if indicator_type in (IndicatorType.ipv4, IndicatorType.ipv6):
        addr = ipaddress.ip_address(v)
        want = 4 if indicator_type is IndicatorType.ipv4 else 6
        if addr.version != want:
            raise ValueError(f"{v} is not an IPv{want} address")
        return str(addr)
    if indicator_type is IndicatorType.domain:
        d = v.lower().rstrip(".")
        if not d or " " in d or "/" in d or "." not in d:
            raise ValueError(f"{raw!r} is not a domain")
        return d
    if indicator_type is IndicatorType.url:
        if "://" not in v:
            raise ValueError(f"{raw!r} is not a URL")
        return v
    if indicator_type in _HEX:
        h = v.lower()
        if len(h) != _HEX[indicator_type] or any(c not in "0123456789abcdef" for c in h):
            raise ValueError(f"{raw!r} is not a {indicator_type.value}")
        return h
    if indicator_type is IndicatorType.email:
        e = v.lower()
        if e.count("@") != 1 or " " in e:
            raise ValueError(f"{raw!r} is not an email")
        return e
    raise ValueError(f"unhandled indicator type {indicator_type}")


def indicator_dedup_key(indicator_type: IndicatorType, value: str, tenant_id: UUID | None) -> str:
    """Global indicators dedup on `(type, value)`; tenant-submitted on
    `(tenant_id, type, value)`."""
    scope = str(tenant_id) if tenant_id is not None else "global"
    return f"{scope}|{indicator_type.value}|{value}"


def freshness_for(
    last_seen: datetime, expires_at: datetime | None, ttl: timedelta, now: datetime
) -> IndicatorFreshness:
    if expires_at is not None and now >= expires_at:
        return IndicatorFreshness.expired
    age = now - last_seen
    if age <= ttl:
        return IndicatorFreshness.fresh
    if age <= 2 * ttl:
        return IndicatorFreshness.aging
    return IndicatorFreshness.stale


class Provenance(SmBaseModel):
    provider: str = Field(min_length=1, max_length=128, description="'<source>' or 'fixture:<name>'.")
    source_kind: TiSourceKind
    reference: str = Field(default="", max_length=512, description="URL / feed line / ticket id.")
    retrieved_at: datetime

    @field_validator("retrieved_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class ThreatIndicator(TimestampedModel):
    id: UUID
    type: IndicatorType
    value: str = Field(min_length=1, max_length=2048, description="Normalized (normalize_indicator_value).")
    tenant_id: UUID | None = Field(default=None, description="NULL = platform-global.")
    source: str = Field(min_length=1, max_length=128)
    confidence: TiConfidence
    reputation: float = Field(ge=0.0, le=1.0, description="Rule-derived, 1 = most malicious.")
    first_seen: datetime
    last_seen: datetime
    expires_at: datetime | None = None
    freshness: IndicatorFreshness
    tags: list[str] = Field(default_factory=list, max_length=32)
    actor_id: str | None = Field(default=None, max_length=64)
    provenance: Provenance

    @field_validator("first_seen", "last_seen", "expires_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else to_utc(v)


class ThreatActor(TimestampedModel):
    id: UUID
    actor_id: str = Field(min_length=1, max_length=64, description="Slug, e.g. 'apt29'.")
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    description: str = Field(default="", max_length=8000)
    source: str = Field(min_length=1, max_length=128)
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    @field_validator("first_seen", "last_seen")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else to_utc(v)


class TiCampaign(TenantScoped, TimestampedModel):
    id: UUID
    name: str = Field(min_length=1, max_length=200)
    actor_id: str | None = Field(default=None, max_length=64)
    description: str = Field(default="", max_length=8000)
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    @field_validator("first_seen", "last_seen")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else to_utc(v)


class TiSource(TimestampedModel):
    id: UUID
    name: str = Field(min_length=1, max_length=128)
    kind: TiSourceKind
    enabled: bool
    ttl_seconds: int = Field(ge=60, description="Fresh window; freshness derives from it.")
    last_poll_at: datetime | None = None
    last_poll_status: str | None = Field(default=None, max_length=64)
    indicator_count: int = Field(default=0, ge=0)

    @field_validator("last_poll_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else to_utc(v)


class EnrichmentMatch(SmBaseModel):
    """One result of the enrichment API — was `{type, value}` a known indicator?"""

    type: IndicatorType
    value: str
    matched: bool
    indicator: ThreatIndicator | None = None
    freshness: IndicatorFreshness | None = None


class TiUpdatePayload(SmBaseModel):
    """`ti.updates` topic event (`EventType.ti_indicator_updated`)."""

    indicator_id: UUID
    type: IndicatorType
    value: str
    tenant_id: UUID | None = None
    source: str = Field(min_length=1, max_length=128)
    action: TiUpdateAction
    confidence: TiConfidence
    freshness: IndicatorFreshness
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


TI_PAYLOADS: dict[EventType, type[SmBaseModel]] = {
    EventType.ti_indicator_updated: TiUpdatePayload,
}

EVENT_PAYLOAD_REGISTRY.update(TI_PAYLOADS)
