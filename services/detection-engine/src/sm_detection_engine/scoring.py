"""Deterministic composite threat score.

The inputs may include ML anomaly scores, but the **combination is deterministic**
(req 8): a fixed, versioned set of weights over named components. If a component
is missing (e.g. `ml-inference` degraded), its weight is dropped and the rest are
renormalised — the score is still well-defined and reproducible, and
`scoring_status` records that it was degraded.

No validated scoring performance is claimed.
"""

from __future__ import annotations

from dataclasses import dataclass

from sm_contracts import ScoringStatus, Severity

__all__ = [
    "SEVERITY_FLOOR",
    "WEIGHTS_VERSION",
    "CompositeScore",
    "composite_score",
    "rule_component",
    "severity_for",
]

WEIGHTS_VERSION = "v1"

# Component weights. Rules are the strongest signal (a rule is a stated fact);
# the statistical detector is always present; the trained model adds lift when
# available.
_WEIGHTS: dict[str, float] = {
    "rule": 0.5,
    "statistical": 0.3,
    "model": 0.2,
}

# A rule hit's severity maps to a rule-component value.
_RULE_VALUE: dict[Severity, float] = {
    Severity.info: 0.2,
    Severity.low: 0.4,
    Severity.medium: 0.65,
    Severity.high: 0.85,
    Severity.critical: 1.0,
}

# The composite score floors the detection severity at least this high.
SEVERITY_FLOOR: tuple[tuple[float, Severity], ...] = (
    (0.9, Severity.critical),
    (0.75, Severity.high),
    (0.55, Severity.medium),
    (0.3, Severity.low),
    (0.0, Severity.info),
)


@dataclass(frozen=True)
class CompositeScore:
    score: float
    components: dict[str, float]
    weights_version: str
    scoring_status: ScoringStatus


def composite_score(
    *,
    rule_value: float | None,
    statistical_normalized: float | None,
    model_normalized: float | None,
) -> CompositeScore:
    raw: dict[str, float | None] = {
        "rule": rule_value,
        "statistical": statistical_normalized,
        "model": model_normalized,
    }
    present = {k: v for k, v in raw.items() if v is not None}
    if not present:
        return CompositeScore(0.0, {}, WEIGHTS_VERSION, ScoringStatus.degraded)

    active_weight = sum(_WEIGHTS[k] for k in present)
    score = sum(_WEIGHTS[k] * v for k, v in present.items()) / active_weight
    status = ScoringStatus.ok if model_normalized is not None else ScoringStatus.degraded
    return CompositeScore(
        score=min(1.0, max(0.0, score)),
        components={k: round(v, 6) for k, v in present.items()},
        weights_version=WEIGHTS_VERSION,
        scoring_status=status,
    )


def rule_component(hit_severities: list[Severity]) -> float | None:
    if not hit_severities:
        return None
    return max(_RULE_VALUE[s] for s in hit_severities)


def severity_for(score: float, rule_severities: list[Severity]) -> Severity:
    by_score = next(sev for floor, sev in SEVERITY_FLOOR if score >= floor)
    by_rule = max(rule_severities, default=Severity.info)
    order = list(Severity)
    return by_score if order.index(by_score) >= order.index(by_rule) else by_rule
