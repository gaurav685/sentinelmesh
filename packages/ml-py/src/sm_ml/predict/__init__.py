"""Deterministic predictive-intelligence heuristics (Phase 13).

    predict_attack_progression(...)  -> PredictionOutcome
    predict_next_action(...)         -> PredictionOutcome
    predict_lateral_movement(...)    -> PredictionOutcome
    predict_threat_trajectory(...)   -> PredictionOutcome

No trained model — see `heuristics.py`. `MODEL_VERSION` names the rule set.
"""

from __future__ import annotations

from .heuristics import (
    MODEL_VERSION,
    PredictionOutcome,
    predict_attack_progression,
    predict_lateral_movement,
    predict_next_action,
    predict_threat_trajectory,
)

__all__ = [
    "MODEL_VERSION",
    "PredictionOutcome",
    "predict_attack_progression",
    "predict_lateral_movement",
    "predict_next_action",
    "predict_threat_trajectory",
]
