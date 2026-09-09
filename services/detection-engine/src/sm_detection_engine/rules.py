"""Rule detectors — deterministic, bounded, and deliberately named as *indicators*.

Each rule is a pure function of the canonical event, its feature vector, and a
small time-bounded context (`EventTimeline`). A rule states a fact ("12 failed
logins for `svc-backup` in 5 minutes") — it does not conclude an attack. MITRE
technique ids are *candidates* for the mapping step (Phase 6), not assertions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sm_contracts import (
    CanonicalEventPayload,
    CanonicalKind,
    EvidenceItem,
    EvidenceKind,
    Severity,
    ThreatSubjectType,
)
from sm_ml import FeatureVector

from .windows import EventTimeline

__all__ = ["RuleContext", "RuleHit", "primary_subject", "run_rules"]


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    title: str
    description: str
    severity: Severity
    technique_ids: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]


@dataclass
class RuleContext:
    tenant_id: UUID
    timeline: EventTimeline
    now: float
    raw_event_id: str
    rule_window_s: int


def primary_subject(canonical: CanonicalEventPayload) -> tuple[ThreatSubjectType, str]:
    a = canonical.actor
    if a is None:
        return ThreatSubjectType.host, "unknown"
    mapping = {
        "identity": ThreatSubjectType.identity,
        "host": ThreatSubjectType.host,
        "ip": ThreatSubjectType.ip,
        "domain": ThreatSubjectType.domain,
    }
    return mapping.get(a.kind.value, ThreatSubjectType.host), a.value


def _ev(rule_id: str, summary: str, detail: dict[str, object], raw_event_id: str) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.rule_match,
        ref=rule_id,
        summary=summary,
        detail=detail,
        provenance=f"detection-engine:{raw_event_id}",
    )


def _feat_ev(fv: FeatureVector, names: list[str], raw_event_id: str) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.feature,
        ref=f"feature_schema:{fv.schema_version}",
        summary="feature values that triggered the rule",
        detail={n: fv.values[n] for n in names},
        provenance=f"detection-engine:{raw_event_id}",
    )


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def _auth_failed_burst(c: CanonicalEventPayload, fv: FeatureVector, ctx: RuleContext) -> list[RuleHit]:
    if c.kind is not CanonicalKind.auth or fv.values.get("is_failure", 0.0) != 1.0 or c.actor is None:
        return []
    principal = c.actor.value
    ctx.timeline.record(ctx.tenant_id, principal, "authfail", at=ctx.now)
    n = ctx.timeline.count(ctx.tenant_id, "authfail", principal, at=ctx.now)
    if n < 5:
        return []
    return [RuleHit(
        rule_id="rule.auth.failed_burst",
        title=f"Repeated authentication failures for {principal}",
        description=f"{n} failed authentications in the last {ctx.rule_window_s}s.",
        severity=Severity.medium if n < 15 else Severity.high,
        technique_ids=("T1110",),
        evidence=(
            _ev("rule.auth.failed_burst",
                f"{n} failed authentications for {principal} within {ctx.rule_window_s}s",
                {"principal": principal, "count": n, "window_s": ctx.rule_window_s},
                ctx.raw_event_id),
        ),
    )]


def _auth_credential_reuse(c: CanonicalEventPayload, fv: FeatureVector, ctx: RuleContext) -> list[RuleHit]:
    if c.kind is not CanonicalKind.auth or fv.values.get("is_failure", 0.0) != 0.0 or c.actor is None:
        return []
    principal = c.actor.value
    host = c.target.value if c.target else "unknown"
    ctx.timeline.record(ctx.tenant_id, f"{principal}|{host}", "authok", at=ctx.now)
    hosts = {s.split("|", 1)[1] for s in ctx.timeline.subjects(ctx.tenant_id, "authok", at=ctx.now)
             if s.startswith(f"{principal}|")}
    if len(hosts) < 3:
        return []
    return [RuleHit(
        rule_id="rule.auth.credential_reuse",
        title=f"{principal} authenticated to {len(hosts)} hosts",
        description=f"{principal} authenticated to {len(hosts)} distinct hosts within "
                    f"{ctx.rule_window_s}s — possible credential reuse / spraying.",
        severity=Severity.medium,
        technique_ids=("T1078", "T1550"),
        evidence=(
            _ev("rule.auth.credential_reuse",
                f"{principal} -> {sorted(hosts)}",
                {"principal": principal, "hosts": sorted(hosts), "window_s": ctx.rule_window_s},
                ctx.raw_event_id),
        ),
    )]


def _lateral_auth_then_egress(
    c: CanonicalEventPayload, fv: FeatureVector, ctx: RuleContext
) -> list[RuleHit]:
    if c.kind is not CanonicalKind.network_flow or c.actor is None:
        return []
    if fv.values.get("direction_outbound", 0.0) != 1.0 or fv.values.get("bytes_sent_log", 0.0) < 14.0:
        return []
    host = c.actor.value
    authed = any(s.endswith(f"|{host}") for s in ctx.timeline.subjects(ctx.tenant_id, "authok", at=ctx.now))
    if not authed:
        return []
    return [RuleHit(
        rule_id="rule.lateral.auth_then_egress",
        title=f"Large outbound transfer from recently-authenticated host {host}",
        description=f"{host} authenticated within {ctx.rule_window_s}s and then sent a large "
                    f"outbound flow — lateral-movement / staging indicator.",
        severity=Severity.medium,
        technique_ids=("T1021", "T1048"),
        evidence=(
            _ev("rule.lateral.auth_then_egress",
                f"outbound flow from {host} after a recent authentication",
                {"host": host, "bytes_sent_log": fv.values["bytes_sent_log"]},
                ctx.raw_event_id),
            _feat_ev(fv, ["bytes_sent_log", "direction_outbound", "dst_port"], ctx.raw_event_id),
        ),
    )]


def _process_suspicious_cmdline(
    c: CanonicalEventPayload, fv: FeatureVector, ctx: RuleContext
) -> list[RuleHit]:
    if c.kind is not CanonicalKind.process_exec:
        return []
    unsigned = fv.values.get("is_signed", 1.0) == 0.0
    high_entropy = fv.values.get("cmdline_entropy", 0.0) > 4.2
    very_long = fv.values.get("cmdline_len", 0.0) > 1000.0
    if not (unsigned and (high_entropy or very_long)):
        return []
    return [RuleHit(
        rule_id="rule.process.suspicious_cmdline",
        title=f"Unsigned process with an unusual command line: {c.target.value if c.target else '?'}",
        description="An unsigned binary executed with a high-entropy or very long command line.",
        severity=Severity.medium,
        technique_ids=("T1059",),
        evidence=(
            _ev("rule.process.suspicious_cmdline",
                "unsigned binary + unusual command line",
                {"unsigned": unsigned, "cmdline_entropy": fv.values.get("cmdline_entropy"),
                 "cmdline_len": fv.values.get("cmdline_len")},
                ctx.raw_event_id),
            _feat_ev(fv, ["is_signed", "cmdline_entropy", "cmdline_len"], ctx.raw_event_id),
        ),
    )]


def _dns_exfil_indicator(
    c: CanonicalEventPayload, fv: FeatureVector, ctx: RuleContext
) -> list[RuleHit]:
    if c.kind is not CanonicalKind.dns:
        return []
    tunnelish = fv.values.get("qname_entropy", 0.0) > 3.6 and fv.values.get("qname_len", 0.0) > 40.0
    txt_probe = fv.values.get("qtype_is_txt", 0.0) == 1.0 and fv.values.get("answer_count", 0.0) == 0.0
    if not (tunnelish or txt_probe):
        return []
    return [RuleHit(
        rule_id="rule.dns.exfil_indicator",
        title=f"DNS query with tunnelling characteristics: {c.target.value if c.target else '?'}",
        description="A long, high-entropy DNS query name or an unanswered TXT probe — "
                    "DNS-tunnelling / exfiltration indicator.",
        severity=Severity.medium,
        technique_ids=("T1071.004", "T1048"),
        evidence=(
            _ev("rule.dns.exfil_indicator",
                "long / high-entropy query name or unanswered TXT probe",
                {"qname_entropy": fv.values.get("qname_entropy"),
                 "qname_len": fv.values.get("qname_len"),
                 "qtype_is_txt": fv.values.get("qtype_is_txt")},
                ctx.raw_event_id),
            _feat_ev(fv, ["qname_entropy", "qname_len", "qtype_is_txt", "answer_count"],
                     ctx.raw_event_id),
        ),
    )]


def _dns_nxdomain_burst(
    c: CanonicalEventPayload, fv: FeatureVector, ctx: RuleContext
) -> list[RuleHit]:
    if c.kind is not CanonicalKind.dns or fv.values.get("is_nxdomain", 0.0) != 1.0 or c.actor is None:
        return []
    client = c.actor.value
    ctx.timeline.record(ctx.tenant_id, client, "nxdomain", at=ctx.now)
    n = ctx.timeline.count(ctx.tenant_id, "nxdomain", client, at=ctx.now)
    if n < 20:
        return []
    return [RuleHit(
        rule_id="rule.dns.nxdomain_burst",
        title=f"NXDOMAIN burst from {client}",
        description=f"{n} NXDOMAIN responses for {client} within {ctx.rule_window_s}s — "
                    f"domain-generation-algorithm / beaconing indicator.",
        severity=Severity.low,
        technique_ids=("T1568.002",),
        evidence=(
            _ev("rule.dns.nxdomain_burst",
                f"{n} NXDOMAIN responses for {client}",
                {"client": client, "count": n, "window_s": ctx.rule_window_s},
                ctx.raw_event_id),
        ),
    )]


_RULES: tuple[Callable[[CanonicalEventPayload, FeatureVector, RuleContext], list[RuleHit]], ...] = (
    _auth_failed_burst,
    _auth_credential_reuse,
    _lateral_auth_then_egress,
    _process_suspicious_cmdline,
    _dns_exfil_indicator,
    _dns_nxdomain_burst,
)


def run_rules(
    canonical: CanonicalEventPayload, features: FeatureVector, ctx: RuleContext
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for rule in _RULES:
        hits.extend(rule(canonical, features, ctx))
    return hits
