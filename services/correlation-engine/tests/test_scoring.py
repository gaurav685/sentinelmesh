from __future__ import annotations

import pytest
from sm_correlation_engine.scoring import (
    CHAIN_SCORE_VERSION,
    chain_confidence,
    chain_progression,
    score_chain,
)

from sm_contracts import CONFIDENCE_CEILING, ScoringStatus, Severity


# ---- progression -----------------------------------------------------
def test_progression_ignores_unknown_and_normalises_to_14() -> None:
    assert chain_progression([]) == 0.0
    assert chain_progression([-1, -1]) == 0.0
    assert chain_progression([7]) == round(8 / 14, 6)          # credential_access reached
    assert chain_progression([7, 9, -1]) == round(10 / 14, 6)  # lateral_movement is furthest


# ---- confidence: probabilistic, never certain ----------------------
def test_confidence_grows_with_distinct_stages_but_never_reaches_1() -> None:
    one = chain_confidence(distinct_real_stages=1, detection_count=1,
                           out_of_order_transitions=0, total_transitions=0, has_strong_signal=False)
    four = chain_confidence(distinct_real_stages=4, detection_count=8,
                            out_of_order_transitions=0, total_transitions=3, has_strong_signal=True)
    assert one < four
    assert four <= CONFIDENCE_CEILING
    huge = chain_confidence(distinct_real_stages=14, detection_count=99,
                            out_of_order_transitions=0, total_transitions=13, has_strong_signal=True)
    assert huge <= CONFIDENCE_CEILING


def test_confidence_is_discounted_when_stages_ran_backwards_in_time() -> None:
    forward = chain_confidence(distinct_real_stages=3, detection_count=3,
                               out_of_order_transitions=0, total_transitions=2, has_strong_signal=False)
    backward = chain_confidence(distinct_real_stages=3, detection_count=3,
                                out_of_order_transitions=2, total_transitions=2, has_strong_signal=False)
    assert backward < forward


# ---- score: deterministic, bounded, documented --------------------
def test_score_is_deterministic() -> None:
    kw = dict(max_severity=Severity.high, max_detection_score=0.7, ti_corroborated=True,
              progression=0.6, confidence=0.7, degraded_evidence=False)
    a = score_chain(**kw)  # type: ignore[arg-type]
    b = score_chain(**kw)  # type: ignore[arg-type]
    assert a == b
    assert a.version == CHAIN_SCORE_VERSION


@pytest.mark.parametrize(
    ("sev", "det", "ti", "prog", "conf"),
    [
        (Severity.info, 0.0, False, 0.0, 0.0),
        (Severity.critical, 1.0, True, 1.0, CONFIDENCE_CEILING),
        (Severity.medium, 0.5, False, 0.5, 0.5),
    ],
)
def test_score_stays_within_0_1(sev: Severity, det: float, ti: bool, prog: float, conf: float) -> None:
    s = score_chain(max_severity=sev, max_detection_score=det, ti_corroborated=ti,
                    progression=prog, confidence=conf, degraded_evidence=False)
    assert 0.0 <= s.score <= 1.0


def test_score_degrades_when_evidence_is_degraded() -> None:
    ok = score_chain(max_severity=Severity.high, max_detection_score=0.7, ti_corroborated=False,
                     progression=0.5, confidence=0.6, degraded_evidence=False)
    deg = score_chain(max_severity=Severity.high, max_detection_score=0.7, ti_corroborated=False,
                      progression=0.5, confidence=0.6, degraded_evidence=True)
    assert ok.scoring_status is ScoringStatus.ok
    assert deg.scoring_status is ScoringStatus.degraded
    assert ok.score == deg.score  # the status flag does not change the number


def test_optional_asset_and_identity_inputs_join_and_renormalise() -> None:
    without = score_chain(max_severity=Severity.medium, max_detection_score=0.4, ti_corroborated=False,
                          progression=0.3, confidence=0.5, degraded_evidence=False)
    assert "asset_criticality" not in without.components
    with_extra = score_chain(max_severity=Severity.medium, max_detection_score=0.4,
                             ti_corroborated=False, progression=0.3, confidence=0.5,
                             degraded_evidence=False, asset_criticality=0.9, identity_risk=0.8)
    assert with_extra.components["asset_criticality"] == 0.9
    assert with_extra.components["identity_risk"] == 0.8
    assert 0.0 <= with_extra.score <= 1.0
    assert with_extra.score > without.score  # high-criticality asset raises the score
