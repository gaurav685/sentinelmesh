"""Deterministic, versioned scoring for an attack chain.

Three numbers, all reproducible from the chain's stored stages — no clock, no
RNG, no model:

- `progression`  — how far along the kill chain the activity has reached.
- `confidence`   — a **probabilistic** estimate that the stages form one
                   coordinated chain rather than unrelated noise. Bounded by
                   `CONFIDENCE_CEILING` (0.95): a chain never claims certainty
                   (Constitution §3).
- `score`        — the chain threat score: a fixed, documented weighting
                   (`CHAIN_SCORE_VERSION`) over severity, anomaly, threat-intel
                   corroboration, progression and confidence. Asset-criticality
                   and identity-risk are accepted as inputs and, when supplied,
                   join the weighting and renormalise it — no asset/identity
                   registry exists yet, so in this phase they are always absent.

No validated scoring performance is claimed anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from sm_contracts import CONFIDENCE_CEILING, N_KILL_CHAIN_STAGES, ScoringStatus, Severity

__all__ = [
    "CHAIN_SCORE_VERSION",
    "ChainScore",
    "chain_confidence",
    "chain_progression",
    "score_chain",
]

CHAIN_SCORE_VERSION = "v1"

_SEVERITY_VALUE: dict[Severity, float] = {
    Severity.info: 0.10,
    Severity.low: 0.30,
    Severity.medium: 0.55,
    Severity.high: 0.80,
    Severity.critical: 1.00,
}

# Core weights (always present).
_CORE_WEIGHTS: dict[str, float] = {
    "severity": 0.30,
    "anomaly": 0.15,
    "threat_intel": 0.15,
    "progression": 0.25,
    "confidence": 0.15,
}
# Optional weights — merged in only when the caller supplies the input.
_OPTIONAL_WEIGHTS: dict[str, float] = {
    "asset_criticality": 0.20,
    "identity_risk": 0.20,
}


def _clamp(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


@dataclass(frozen=True)
class ChainScore:
    score: float
    components: dict[str, float]
    version: str
    scoring_status: ScoringStatus


def chain_progression(stage_orders: list[int]) -> float:
    """`(furthest kill-chain position reached + 1) / 14`. `unknown` stages
    (order -1) do not count."""
    real = [o for o in stage_orders if o >= 0]
    if not real:
        return 0.0
    return round((max(real) + 1) / N_KILL_CHAIN_STAGES, 6)


def chain_confidence(
    *,
    distinct_real_stages: int,
    detection_count: int,
    out_of_order_transitions: int,
    total_transitions: int,
    has_strong_signal: bool,
) -> float:
    """Probabilistic — never a certainty.

    - grows with the number of distinct real stages (one stage is barely a chain;
      several ordered stages is a strong signal),
    - is discounted when stage transitions ran backwards in time
      (`out_of_order_transitions` / `total_transitions`),
    - gets a small bump for a high-severity or TI-corroborated member and for a
      well-populated chain.
    """
    if distinct_real_stages <= 0:
        base = 0.10
    else:
        base = min(0.80, 0.25 + 0.18 * (distinct_real_stages - 1))
    order_factor = 1.0 if total_transitions == 0 else 1.0 - out_of_order_transitions / total_transitions
    conf = base * (0.7 + 0.3 * order_factor)
    if has_strong_signal:
        conf += 0.05
    if detection_count >= 5:
        conf += 0.03
    return round(min(CONFIDENCE_CEILING, _clamp(conf)), 6)


def score_chain(
    *,
    max_severity: Severity,
    max_detection_score: float,
    ti_corroborated: bool,
    progression: float,
    confidence: float,
    degraded_evidence: bool,
    asset_criticality: float | None = None,
    identity_risk: float | None = None,
) -> ChainScore:
    components: dict[str, float] = {
        "severity": _SEVERITY_VALUE[max_severity],
        "anomaly": round(_clamp(max_detection_score), 6),
        "threat_intel": 1.0 if ti_corroborated else 0.0,
        "progression": round(_clamp(progression), 6),
        "confidence": round(_clamp(confidence), 6),
    }
    weights = dict(_CORE_WEIGHTS)
    if asset_criticality is not None:
        components["asset_criticality"] = round(_clamp(asset_criticality), 6)
        weights["asset_criticality"] = _OPTIONAL_WEIGHTS["asset_criticality"]
    if identity_risk is not None:
        components["identity_risk"] = round(_clamp(identity_risk), 6)
        weights["identity_risk"] = _OPTIONAL_WEIGHTS["identity_risk"]

    active_weight = sum(weights[k] for k in components)
    score = sum(weights[k] * v for k, v in components.items()) / active_weight

    status = ScoringStatus.degraded if degraded_evidence else ScoringStatus.ok
    return ChainScore(
        score=round(_clamp(score), 6),
        components=components,
        version=CHAIN_SCORE_VERSION,
        scoring_status=status,
    )
