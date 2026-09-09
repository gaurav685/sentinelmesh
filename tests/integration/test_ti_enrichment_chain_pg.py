"""Phase 6 Unit 5 — real PostgreSQL: the enrichment chain end to end.

A global IOC seeded in `threat-intel-service`'s store -> the normalization-engine
`ThreatIntelEnricher` calls the real `POST /api/v1/ti/enrich` over ASGI ->
`canonical.enrichment["threat_intel"]` is populated with provenance ->
`detection-engine`'s rules raise `rule.ti.known_bad_indicator` with a
`ti_indicator` evidence item. No fabrication: a value that is not in the store
produces no match and no rule hit.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sm_detection_engine.rules import RuleContext, run_rules
from sm_detection_engine.windows import EventTimeline
from sm_ti_service.app import create_app as create_ti_app
from sm_ti_service.deps import Services as TiServices
from sm_ti_service.metrics import TiMetrics
from sm_ti_service.store import IndicatorInput, IndicatorRepository

from sm_common.db import Database
from sm_common.observability import build_metrics
from sm_contracts import (
    CanonicalEventPayload,
    CanonicalKind,
    EntityRef,
    EventType,
    EvidenceKind,
    IndicatorType,
    Severity,
    TiConfidence,
    TiSourceKind,
)
from sm_ml import extract_features
from sm_normalization_engine.enrich.threat_intel import ThreatIntelEnricher

from .conftest import integration_settings

pytestmark = pytest.mark.integration

_SIGNING_KEY = "integration-signing-key-0123456789"  # integration_settings() default


class _FakeProducer:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...

    async def send(self, *_a: object, **_kw: object) -> None: ...


class _FakeBackground:
    def stop(self) -> None: ...
    async def run(self) -> None: ...


def _ti_client(db: Database) -> httpx.AsyncClient:
    settings = integration_settings(service_name="threat-intel-service")
    base = build_metrics("threat-intel-service")
    services = TiServices(
        settings=settings, metrics=base, ti_metrics=TiMetrics(base, "threat-intel-service"),
        db=db, repo=IndicatorRepository(db, default_ttl_seconds=3600),
        producer=_FakeProducer(),  # type: ignore[arg-type]
        sweeper=_FakeBackground(),  # type: ignore[arg-type]
        poller=_FakeBackground(),  # type: ignore[arg-type]
    )
    app = create_ti_app(services=services)
    # httpx's ASGITransport does not run lifespan events, so wire state directly.
    app.state.services = services
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://ti.test")


def _canonical(actor: EntityRef, target: EntityRef) -> CanonicalEventPayload:
    return CanonicalEventPayload(
        kind=CanonicalKind.network_flow, occurred_at=datetime.now(UTC) - timedelta(seconds=1),
        action="connected_to", outcome="allow", actor=actor, target=target,
        entities=[actor, target], raw_event_id=uuid.uuid4(),
        raw_event_type=EventType.telemetry_network_flow,
        attributes={"direction": "outbound", "bytes_sent": 4000, "protocol": "tcp"},
    )


def _rule_ctx() -> RuleContext:
    return RuleContext(
        tenant_id=uuid.uuid4(), timeline=EventTimeline(window_s=300), now=time.time(),
        raw_event_id="raw-1", rule_window_s=300,
    )


async def test_seeded_ioc_flows_through_enrichment_into_a_detection(clean: Database) -> None:
    repo = IndicatorRepository(clean, default_ttl_seconds=3600)
    await repo.upsert(IndicatorInput(
        type=IndicatorType.ipv4, value="198.51.100.23", source="fixture:demo",
        source_kind=TiSourceKind.fixture, confidence=TiConfidence.high, tags=["c2", "malware"],
    ))

    async with _ti_client(clean) as http:
        enricher = ThreatIntelEnricher(
            http, base_url="http://ti.test", signing_key=_SIGNING_KEY, timeout_s=5.0
        )
        actor = EntityRef(kind="ip", value="198.51.100.23")
        target = EntityRef(kind="domain", value="host.example")
        payload = _canonical(actor, target)
        enrichment = await enricher.enrich(payload)

    ti = enrichment["threat_intel"]
    assert ti["provider"] == "threat-intel-service"
    assert [m["value"] for m in ti["matches"]] == ["198.51.100.23"]
    assert ti["matches"][0]["reputation"] is not None
    assert ti["matches"][0]["freshness"] == "fresh"

    enriched = payload.model_copy(update={"enrichment": enrichment})
    hits = run_rules(enriched, extract_features(enriched), _rule_ctx())
    ti_hit = next(h for h in hits if h.rule_id == "rule.ti.known_bad_indicator")
    assert ti_hit.severity is Severity.high  # reputation of a high-confidence c2 IOC >= 0.75
    ev = next(e for e in ti_hit.evidence if e.kind is EvidenceKind.ti_indicator)
    assert "threat-intel-service" in ev.provenance
    assert ev.detail["matches"][0]["value"] == "198.51.100.23"


async def test_unknown_indicator_yields_no_match_and_no_rule_hit(clean: Database) -> None:
    async with _ti_client(clean) as http:
        enricher = ThreatIntelEnricher(
            http, base_url="http://ti.test", signing_key=_SIGNING_KEY, timeout_s=5.0
        )
        actor = EntityRef(kind="ip", value="203.0.113.200")
        target = EntityRef(kind="domain", value="clean.example")
        payload = _canonical(actor, target)
        enrichment = await enricher.enrich(payload)

    assert enrichment == {}
    hits = run_rules(payload, extract_features(payload), _rule_ctx())
    assert not any(h.rule_id == "rule.ti.known_bad_indicator" for h in hits)
