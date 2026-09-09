from __future__ import annotations

import time

from sm_detection_engine.rules import RuleContext, run_rules
from sm_detection_engine.windows import EventTimeline

from sm_contracts import CanonicalKind, EvidenceKind, Severity
from sm_ml import extract_features

from .conftest import TENANT_ID, canonical


def _ctx(timeline: EventTimeline, *, now: float | None = None) -> RuleContext:
    return RuleContext(
        tenant_id=TENANT_ID, timeline=timeline, now=now or time.time(),
        raw_event_id="raw-1", rule_window_s=300,
    )


def _run(kind: CanonicalKind, ctx: RuleContext, **kw: object) -> list[str]:
    env = canonical(kind, **kw)  # type: ignore[arg-type]
    fv = extract_features(env.payload)
    return [h.rule_id for h in run_rules(env.payload, fv, ctx)]


def test_failed_auth_burst_needs_five_in_the_window() -> None:
    tl = EventTimeline(window_s=300)
    ctx = _ctx(tl, now=1000.0)
    for _ in range(4):
        assert _run(CanonicalKind.auth, ctx, outcome="failure", actor=("identity", "alice"),
                    action="authentication_failed") == []
    assert "rule.auth.failed_burst" in _run(
        CanonicalKind.auth, ctx, outcome="failure", actor=("identity", "alice"),
        action="authentication_failed",
    )


def test_failed_auth_burst_respects_the_time_window() -> None:
    tl = EventTimeline(window_s=60)
    for k in range(5):
        _run(CanonicalKind.auth, _ctx(tl, now=1000.0 + k), outcome="failure",
             actor=("identity", "bob"), action="authentication_failed")
    # 200s later the old failures have aged out
    assert _run(CanonicalKind.auth, _ctx(tl, now=1200.0), outcome="failure",
                actor=("identity", "bob"), action="authentication_failed") == []


def test_credential_reuse_across_three_hosts() -> None:
    tl = EventTimeline(window_s=300)
    ctx = _ctx(tl, now=1000.0)
    for host in ("web01", "web02"):
        assert _run(CanonicalKind.auth, ctx, outcome="success", actor=("identity", "carol"),
                    target=("host", host), action="authentication_succeeded") == []
    assert "rule.auth.credential_reuse" in _run(
        CanonicalKind.auth, ctx, outcome="success", actor=("identity", "carol"),
        target=("host", "web03"), action="authentication_succeeded",
    )


def test_lateral_movement_needs_a_prior_auth_and_a_large_flow() -> None:
    tl = EventTimeline(window_s=300)
    ctx = _ctx(tl, now=1000.0)
    # a large outbound flow with no prior auth: nothing
    assert _run(CanonicalKind.network_flow, ctx, actor=("host", "web01"), target=("ip", "9.9.9.9"),
                action="connected_to", attributes={"direction": "outbound", "bytes_sent": 5_000_000,
                                                   "protocol": "tcp"}) == []
    # now authenticate that host, then repeat
    _run(CanonicalKind.auth, ctx, outcome="success", actor=("identity", "d"),
         target=("host", "web01"), action="authentication_succeeded")
    assert "rule.lateral.auth_then_egress" in _run(
        CanonicalKind.network_flow, ctx, actor=("host", "web01"), target=("ip", "9.9.9.9"),
        action="connected_to",
        attributes={"direction": "outbound", "bytes_sent": 5_000_000, "protocol": "tcp"},
    )


def test_suspicious_process_cmdline() -> None:
    ctx = _ctx(EventTimeline(window_s=300))
    clean = _run(CanonicalKind.process_exec, ctx, actor=("host", "h"), target=("process", "svchost.exe"),
                 action="executed", attributes={"signed": True, "command_line": "svchost.exe -k netsvcs"})
    assert clean == []
    hostile = _run(
        CanonicalKind.process_exec, ctx, actor=("host", "h"), target=("process", "p.exe"),
        action="executed",
        attributes={"signed": False, "command_line": "powershell -enc " + "kQ7wZ2xR9tB4" * 130},
    )
    assert "rule.process.suspicious_cmdline" in hostile


def test_dns_tunnelling_indicator() -> None:
    ctx = _ctx(EventTimeline(window_s=300))
    normal = _run(CanonicalKind.dns, ctx, actor=("ip", "10.0.0.1"),
                  target=("domain", "www.example.com"), action="resolved",
                  attributes={"query_type": "A", "answers": ["93.184.216.34"]})
    assert normal == []
    tunnel = _run(
        CanonicalKind.dns, ctx, actor=("ip", "10.0.0.1"),
        target=("domain", "a8f3k2j9x1q7w4z5m0p6r3t8.tunnel.evil.example.com"),
        action="resolved", attributes={"query_type": "TXT", "answers": []},
    )
    assert "rule.dns.exfil_indicator" in tunnel


def _ti_enrichment(*matches: dict[str, object]) -> dict[str, object]:
    return {"threat_intel": {"provider": "threat-intel-service",
                             "as_of": "2026-09-09T00:00:00+00:00", "matches": list(matches)}}


def test_ti_known_bad_indicator_fires_with_ti_evidence() -> None:
    ctx = _ctx(EventTimeline(window_s=300))
    env = canonical(
        CanonicalKind.network_flow, actor=("ip", "198.51.100.23"),
        target=("domain", "malware-delivery.example"), action="connected_to",
        enrichment=_ti_enrichment(
            {"type": "ipv4", "value": "198.51.100.23", "reputation": 0.9,
             "confidence": "high", "source": "fixture", "freshness": "fresh"},
        ),
    )
    hits = run_rules(env.payload, extract_features(env.payload), ctx)
    ti = next(h for h in hits if h.rule_id == "rule.ti.known_bad_indicator")
    assert ti.severity is Severity.high  # reputation >= 0.75
    assert ti.technique_ids == ()  # a TI hit is not itself a technique
    assert any(e.kind is EvidenceKind.ti_indicator for e in ti.evidence)
    ev = next(e for e in ti.evidence if e.kind is EvidenceKind.ti_indicator)
    assert "threat-intel-service" in ev.provenance


def test_ti_known_bad_indicator_severity_scales_with_reputation() -> None:
    ctx = _ctx(EventTimeline(window_s=300))
    env = canonical(
        CanonicalKind.network_flow, actor=("ip", "203.0.113.7"), action="connected_to",
        enrichment=_ti_enrichment(
            {"type": "ipv4", "value": "203.0.113.7", "reputation": 0.5, "freshness": "aging"},
        ),
    )
    hits = run_rules(env.payload, extract_features(env.payload), ctx)
    ti = next(h for h in hits if h.rule_id == "rule.ti.known_bad_indicator")
    assert ti.severity is Severity.medium


def test_ti_rule_silent_without_a_match() -> None:
    ctx = _ctx(EventTimeline(window_s=300))
    env = canonical(CanonicalKind.network_flow, actor=("ip", "203.0.113.7"), action="connected_to",
                    enrichment=_ti_enrichment())
    hits = run_rules(env.payload, extract_features(env.payload), ctx)
    assert not any(h.rule_id == "rule.ti.known_bad_indicator" for h in hits)


def test_rule_severities_are_bounded() -> None:
    tl = EventTimeline(window_s=300)
    ctx = _ctx(tl, now=1000.0)
    hits: list[Severity] = []
    for _ in range(20):
        env = canonical(CanonicalKind.auth, outcome="failure", actor=("identity", "e"),
                        action="authentication_failed")
        fv = extract_features(env.payload)
        hits = [h.severity for h in run_rules(env.payload, fv, ctx)]
    assert Severity.high in hits  # 15+ failures escalates
