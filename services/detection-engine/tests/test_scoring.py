from __future__ import annotations

from sm_detection_engine.scoring import composite_score, rule_component, severity_for

from sm_contracts import ScoringStatus, Severity


def test_composite_renormalises_over_present_components() -> None:
    # only the statistical component present -> its normalized value is the score
    c = composite_score(rule_value=None, statistical_normalized=0.8, model_normalized=None)
    assert c.score == 0.8
    assert c.scoring_status is ScoringStatus.degraded  # no model
    assert set(c.components) == {"statistical"}


def test_composite_is_ok_only_when_the_model_contributed() -> None:
    c = composite_score(rule_value=0.6, statistical_normalized=0.4, model_normalized=0.5)
    assert c.scoring_status is ScoringStatus.ok
    assert 0.0 <= c.score <= 1.0
    assert set(c.components) == {"rule", "statistical", "model"}


def test_composite_with_nothing_is_zero_and_degraded() -> None:
    c = composite_score(rule_value=None, statistical_normalized=None, model_normalized=None)
    assert c.score == 0.0
    assert c.scoring_status is ScoringStatus.degraded


def test_rule_component_takes_the_max_severity() -> None:
    assert rule_component([]) is None
    assert rule_component([Severity.low, Severity.high]) == rule_component([Severity.high])


def test_severity_is_the_higher_of_score_and_rule() -> None:
    assert severity_for(0.95, []) is Severity.critical
    assert severity_for(0.1, [Severity.high]) is Severity.high
    assert severity_for(0.8, [Severity.low]) is Severity.high
