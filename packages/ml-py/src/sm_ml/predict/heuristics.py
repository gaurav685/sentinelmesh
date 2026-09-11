"""Deterministic predictive-intelligence heuristics (Phase 13).

**There is no trained predictive model in this build** (R15's status: no
dataset/training run has produced one — Constitution §3, §13). Every
function here is a deterministic rule over data the platform already has —
the current kill-chain position, a subject's own historical technique set,
fingerprint similarity, campaign activity — never a learned probability.
`MODEL_VERSION = "heuristic-v1"` says so explicitly; nothing here is
presented as more certain than a documented rule justifies. When the input
does not support a prediction, the function returns `confidence=0.0` and
says so in `prediction`, never a guess.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sm_contracts import STAGE_ORDER, AttackStage

from ..memory import cosine_similarity, technique_feature_vector

__all__ = [
    "MODEL_VERSION",
    "PredictionOutcome",
    "predict_attack_progression",
    "predict_lateral_movement",
    "predict_next_action",
    "predict_threat_trajectory",
]

MODEL_VERSION = "heuristic-v1"

_STAGE_BY_ORDER: dict[int, AttackStage] = {v: k for k, v in STAGE_ORDER.items() if v >= 0}
_MAX_STAGE_ORDER = max(_STAGE_BY_ORDER)


@dataclass(frozen=True)
class PredictionOutcome:
    prediction: str
    #: `[0, 1]`. `0.0` means "no prediction" — the caller should present this
    #: as "no prediction", not as a low-confidence guess.
    confidence: float
    evidence: tuple[str, ...] = field(default_factory=tuple)
    features: dict[str, float | int | str] = field(default_factory=dict)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def predict_attack_progression(
    *, latest_stage: AttackStage, distinct_stage_count: int, chain_score: float, chain_confidence: float,
) -> PredictionOutcome:
    """The next kill-chain stage after `latest_stage`, if any."""
    pos = STAGE_ORDER[latest_stage]
    features: dict[str, float | int | str] = {
        "latest_stage_order": pos, "distinct_stage_count": distinct_stage_count,
        "chain_score": chain_score, "chain_confidence": chain_confidence,
    }
    if pos < 0:
        return PredictionOutcome(
            "unknown — no kill-chain stage established yet", 0.0,
            ("latest_stage is 'unknown': no technique has been mapped to a stage",), features,
        )
    if pos >= _MAX_STAGE_ORDER:
        return PredictionOutcome(
            "none — already at the final kill-chain stage", 0.0,
            (f"latest_stage={latest_stage.value} is the last stage",), features,
        )
    next_stage = _STAGE_BY_ORDER[pos + 1]
    confidence = _clamp(chain_confidence * (0.6 + 0.05 * distinct_stage_count))
    return PredictionOutcome(
        next_stage.value, confidence,
        (
            f"latest_stage={latest_stage.value}", f"distinct_stage_count={distinct_stage_count}",
            f"chain_score={chain_score:.3f}", f"chain_confidence={chain_confidence:.3f}",
        ),
        features,
    )


def predict_next_action(
    *, pattern_technique_ids: Sequence[str], chain_technique_ids: Sequence[str],
) -> PredictionOutcome:
    """A technique this subject has used before but has not used yet in the
    current chain — grounded in the subject's own history, never a guess
    about an unobserved technique."""
    candidates = sorted(set(pattern_technique_ids) - set(chain_technique_ids))
    features: dict[str, float | int | str] = {
        "pattern_technique_count": len(set(pattern_technique_ids)),
        "chain_technique_count": len(set(chain_technique_ids)),
        "candidate_count": len(candidates),
    }
    if not candidates:
        return PredictionOutcome(
            "none — no technique in this subject's history is unseen in the current chain",
            0.0, ("pattern_technique_ids ⊆ chain_technique_ids",), features,
        )
    predicted = candidates[0]
    confidence = _clamp(0.2 + 0.05 * len(pattern_technique_ids))
    return PredictionOutcome(
        predicted, confidence,
        (
            f"seen before for this subject, not yet in this chain: {predicted}",
            f"pattern_technique_count={len(set(pattern_technique_ids))}",
        ),
        features,
    )


def predict_lateral_movement(
    *, subject_technique_ids: Sequence[str],
    candidates: Sequence[tuple[str, str, Sequence[str]]],
) -> PredictionOutcome:
    """The other subject (by fingerprint technique-similarity) most likely
    to be the next lateral-movement target, from already-recorded
    adversary fingerprints — not a live graph traversal."""
    features: dict[str, float | int | str] = {"candidate_count": len(candidates)}
    if not candidates:
        return PredictionOutcome(
            "none — no other adversary fingerprint recorded for this tenant", 0.0,
            ("candidates is empty",), features,
        )
    query_vec = technique_feature_vector(subject_technique_ids)
    best_subject: str | None = None
    best_sim = -1.0
    for subject_type, subject_id, technique_ids in candidates:
        sim = cosine_similarity(technique_feature_vector(technique_ids), query_vec)
        if sim > best_sim:
            best_sim, best_subject = sim, f"{subject_type}:{subject_id}"
    features["best_similarity"] = round(best_sim, 6)
    if best_subject is None or best_sim <= 0.0:
        return PredictionOutcome(
            "none — no candidate shares a technique with this subject", 0.0,
            ("every candidate's cosine similarity was <= 0",), features,
        )
    return PredictionOutcome(
        best_subject, _clamp(best_sim),
        (f"technique-overlap similarity to {best_subject} = {best_sim:.3f}",), features,
    )


def predict_threat_trajectory(*, status: str, chain_count: int) -> PredictionOutcome:
    """A campaign's overall direction: escalating / active / stalling /
    concluded — from its own recorded status and chain count, never a
    forecast beyond what has already happened."""
    features: dict[str, float | int | str] = {"status": status, "chain_count": chain_count}
    evidence = (f"status={status}", f"chain_count={chain_count}")
    if status == "closed":
        return PredictionOutcome("concluded", 0.9, evidence, features)
    if status == "dormant":
        return PredictionOutcome("stalling", 0.6, evidence, features)
    if chain_count >= 3:
        return PredictionOutcome("escalating", 0.7, evidence, features)
    if chain_count >= 1:
        return PredictionOutcome("active", 0.5, evidence, features)
    return PredictionOutcome("unknown — no chains recorded yet", 0.0, evidence, features)
