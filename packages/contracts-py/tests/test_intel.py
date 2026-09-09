from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sm_contracts import (
    EVENT_PAYLOAD_REGISTRY,
    AttackMatrixVersion,
    AttackTechnique,
    EventType,
    IndicatorFreshness,
    IndicatorType,
    Provenance,
    ThreatIndicator,
    TiConfidence,
    TiSourceKind,
    TiUpdateAction,
    TiUpdatePayload,
    freshness_for,
    indicator_dedup_key,
    is_technique_id,
    normalize_indicator_value,
    parent_technique_id,
)

_NOW = datetime.now(UTC)


# ---- indicator normalisation (TB-4: reject, never fabricate) -----------
@pytest.mark.parametrize(
    ("itype", "raw", "want"),
    [
        (IndicatorType.ipv4, "  192.168.1.1  ", "192.168.1.1"),
        (IndicatorType.ipv6, "2001:DB8::1", "2001:db8::1"),
        (IndicatorType.domain, "Evil.Example.COM.", "evil.example.com"),
        (IndicatorType.sha256, "A" * 64, "a" * 64),
        (IndicatorType.email, "Bad@Actor.com", "bad@actor.com"),
        (IndicatorType.url, "http://evil.example.com/x", "http://evil.example.com/x"),
    ],
)
def test_normalize_indicator_value(itype: IndicatorType, raw: str, want: str) -> None:
    assert normalize_indicator_value(itype, raw) == want


@pytest.mark.parametrize(
    ("itype", "raw"),
    [
        (IndicatorType.ipv4, "2001:db8::1"),
        (IndicatorType.ipv4, "999.1.1.1"),
        (IndicatorType.domain, "no-dot"),
        (IndicatorType.sha256, "abc"),
        (IndicatorType.email, "two@@at.com"),
        (IndicatorType.url, "evil.example.com"),
    ],
)
def test_normalize_rejects_malformed(itype: IndicatorType, raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_indicator_value(itype, raw)


def test_dedup_key_scopes_global_vs_tenant() -> None:
    t = uuid.uuid4()
    g = indicator_dedup_key(IndicatorType.domain, "evil.example.com", None)
    scoped = indicator_dedup_key(IndicatorType.domain, "evil.example.com", t)
    assert g.startswith("global|") and scoped.startswith(f"{t}|")
    assert g != scoped


# ---- freshness ------------------------------------------------------
def test_freshness_transitions() -> None:
    ttl = timedelta(hours=24)
    ls = _NOW - timedelta(hours=1)
    assert freshness_for(ls, None, ttl, _NOW) is IndicatorFreshness.fresh
    assert freshness_for(_NOW - timedelta(hours=30), None, ttl, _NOW) is IndicatorFreshness.aging
    assert freshness_for(_NOW - timedelta(hours=60), None, ttl, _NOW) is IndicatorFreshness.stale
    assert freshness_for(ls, _NOW - timedelta(minutes=1), ttl, _NOW) is IndicatorFreshness.expired


# ---- payload / registry -------------------------------------------
def test_ti_update_payload_registered_and_round_trips() -> None:
    p = TiUpdatePayload(
        indicator_id=uuid.uuid4(), type=IndicatorType.ipv4, value="1.2.3.4",
        source="fixture:demo", action=TiUpdateAction.added, confidence=TiConfidence.high,
        freshness=IndicatorFreshness.fresh, observed_at=_NOW,
    )
    assert TiUpdatePayload.model_validate_json(p.model_dump_json()) == p
    assert EVENT_PAYLOAD_REGISTRY[EventType.ti_indicator_updated] is TiUpdatePayload


def test_indicator_reputation_bounds() -> None:
    prov = Provenance(provider="fixture:demo", source_kind=TiSourceKind.fixture, retrieved_at=_NOW)
    with pytest.raises(ValidationError):
        ThreatIndicator(
            id=uuid.uuid4(), created_at=_NOW, updated_at=_NOW, type=IndicatorType.ipv4,
            value="1.2.3.4", source="fixture:demo", confidence=TiConfidence.low,
            reputation=1.5, first_seen=_NOW, last_seen=_NOW,
            freshness=IndicatorFreshness.fresh, provenance=prov,
        )


# ---- MITRE ---------------------------------------------------------
def test_technique_id_helpers() -> None:
    assert is_technique_id("T1110") and is_technique_id("T1110.001")
    assert not is_technique_id("TA0001") and not is_technique_id("1110")
    assert parent_technique_id("T1110.001") == "T1110"
    assert parent_technique_id("T1110") is None


def test_attack_technique_rejects_a_bad_id() -> None:
    with pytest.raises(ValidationError):
        AttackTechnique(technique_id="X999", name="n", matrix_version="14.1")


def test_matrix_version_needs_a_real_bundle_hash() -> None:
    with pytest.raises(ValidationError):
        AttackMatrixVersion(
            version="14.1", source="mitre/enterprise", imported_at=_NOW,
            tactic_count=14, technique_count=200, subtechnique_count=400,
            stix_bundle_sha256="not-a-hash",
        )
