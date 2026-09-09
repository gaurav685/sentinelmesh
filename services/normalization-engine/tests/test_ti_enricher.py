from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import respx

from sm_contracts import CanonicalEventPayload, CanonicalKind, EntityRef, EventType
from sm_normalization_engine.enrich.threat_intel import ThreatIntelEnricher

_URL = "http://ti.test"


def _canonical(**over: object) -> CanonicalEventPayload:
    actor = EntityRef(kind="ip", value="198.51.100.23")
    target = EntityRef(kind="domain", value="malware-delivery.example")
    base: dict[str, object] = dict(
        kind=CanonicalKind.network_flow, occurred_at=datetime.now(UTC), action="connected_to",
        outcome="allow", actor=actor, target=target, entities=[actor, target],
        raw_event_id=uuid.uuid4(), raw_event_type=EventType.telemetry_network_flow, attributes={},
    )
    base.update(over)
    return CanonicalEventPayload(**base)  # type: ignore[arg-type]


def _enricher() -> ThreatIntelEnricher:
    return ThreatIntelEnricher(
        httpx.AsyncClient(), base_url=_URL, signing_key="k" * 40, timeout_s=2.0,
    )


def test_lookups_cover_ip_domain_and_hash() -> None:
    ev = _canonical(attributes={"hash_sha256": "a" * 64})
    got = _enricher()._lookups(ev)
    assert {(i["type"], i["value"]) for i in got} == {
        ("ipv4", "198.51.100.23"),
        ("domain", "malware-delivery.example"),
        ("sha256", "a" * 64),
    }


@respx.mock
async def test_hit_produces_a_provenance_carrying_enrichment() -> None:
    respx.post(f"{_URL}/api/v1/ti/enrich").mock(return_value=httpx.Response(200, json={"results": [
        {"type": "ipv4", "value": "198.51.100.23", "matched": True, "freshness": "fresh",
         "indicator": {"confidence": "high", "reputation": 0.9, "source": "fixture"}},
        {"type": "domain", "value": "malware-delivery.example", "matched": False},
    ]}))
    out = await _enricher().enrich(_canonical())
    ti = out["threat_intel"]
    assert ti["provider"] == "threat-intel-service"
    assert len(ti["matches"]) == 1
    assert ti["matches"][0]["reputation"] == 0.9


@respx.mock
async def test_miss_leaves_the_key_absent() -> None:
    respx.post(f"{_URL}/api/v1/ti/enrich").mock(
        return_value=httpx.Response(200, json={"results": [
            {"type": "ipv4", "value": "198.51.100.23", "matched": False},
        ]})
    )
    assert await _enricher().enrich(_canonical()) == {}


@respx.mock
async def test_ti_service_outage_returns_empty_not_an_error() -> None:
    respx.post(f"{_URL}/api/v1/ti/enrich").mock(side_effect=httpx.ConnectError("down"))
    assert await _enricher().enrich(_canonical()) == {}


async def test_no_lookup_entities_skips_the_call() -> None:
    ev = _canonical(actor=None, target=None, entities=[])
    assert await _enricher().enrich(ev) == {}
