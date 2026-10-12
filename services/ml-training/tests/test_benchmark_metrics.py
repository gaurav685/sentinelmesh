from __future__ import annotations

import pytest
from sm_ml_training.benchmark.metrics import (
    bootstrap_ci,
    confusion_counts,
    per_class_recall,
    pr_auc,
    precision_recall_f1_fpr,
    recall_at_fpr,
    roc_auc,
    threshold_at_fpr,
)


def test_roc_auc_perfect_separation_is_one() -> None:
    scores = [0.1, 0.2, 0.3, 0.9, 0.95, 1.0]
    labels = [0, 0, 0, 1, 1, 1]
    assert roc_auc(scores, labels) == pytest.approx(1.0)


def test_roc_auc_perfect_reversal_is_zero() -> None:
    scores = [0.9, 0.95, 1.0, 0.1, 0.2, 0.3]
    labels = [0, 0, 0, 1, 1, 1]
    assert roc_auc(scores, labels) == pytest.approx(0.0)


def test_roc_auc_identical_scores_is_one_half() -> None:
    scores = [0.5, 0.5, 0.5, 0.5]
    labels = [0, 1, 0, 1]
    assert roc_auc(scores, labels) == pytest.approx(0.5)


def test_roc_auc_matches_a_hand_worked_tie_case() -> None:
    scores = [1.0, 2.0, 2.0, 3.0]
    labels = [0, 1, 0, 1]
    # ranks (1-indexed, tie-averaged): 1.0 -> 1, 2.0 (x2) -> 2.5 each, 3.0 -> 4
    # positive-label ranks: index1 (score=2.0) -> 2.5; index3 (score=3.0) -> 4
    # sum_ranks_pos = 6.5; n_pos=2, n_neg=2
    # auc = (sum_ranks_pos - n_pos*(n_pos+1)/2) / (n_pos*n_neg) = (6.5-3)/4 = 0.875
    assert roc_auc(scores, labels) == pytest.approx(0.875)


def test_roc_auc_requires_both_classes() -> None:
    with pytest.raises(ValueError, match="undefined"):
        roc_auc([0.1, 0.2], [1, 1])


def test_confusion_counts() -> None:
    preds = [1, 1, 0, 0]
    labels = [1, 0, 0, 1]
    assert confusion_counts(preds, labels) == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}


def test_precision_recall_f1_fpr() -> None:
    preds = [1, 1, 0, 0, 0]
    labels = [1, 0, 0, 0, 1]
    m = precision_recall_f1_fpr(preds, labels)
    # tp=1, fp=1, tn=2, fn=1
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["f1"] == pytest.approx(0.5)
    assert m["false_positive_rate"] == pytest.approx(1 / 3)


def test_precision_recall_f1_fpr_all_zero_when_no_positives_predicted() -> None:
    preds = [0, 0, 0]
    labels = [0, 1, 0]
    m = precision_recall_f1_fpr(preds, labels)
    assert m == {"precision": 0.0, "recall": 0.0, "f1": 0.0, "false_positive_rate": 0.0}


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError):
        roc_auc([0.1, 0.2], [1])
    with pytest.raises(ValueError):
        confusion_counts([1], [1, 0])


def test_pr_auc_perfect_separation_is_one() -> None:
    scores = [0.1, 0.2, 0.3, 0.9, 0.95, 1.0]
    labels = [0, 0, 0, 1, 1, 1]
    assert pr_auc(scores, labels) == pytest.approx(1.0)


def test_pr_auc_no_positives_raises() -> None:
    with pytest.raises(ValueError, match="no positive labels"):
        pr_auc([0.1, 0.2], [0, 0])


def test_recall_at_fpr_perfect_separation_hits_full_recall_at_zero_fpr() -> None:
    scores = [0.1, 0.2, 0.3, 0.9, 0.95, 1.0]
    labels = [0, 0, 0, 1, 1, 1]
    assert recall_at_fpr(scores, labels, target_fpr=0.0) == pytest.approx(1.0)


def test_recall_at_fpr_caps_false_alarms() -> None:
    # One negative scores higher than all but the top positive -- at
    # fpr=0.0 that negative must stay excluded, costing real recall.
    scores = [0.1, 0.2, 0.85, 0.9, 0.5, 1.0]
    labels = [0, 0, 0, 1, 1, 1]
    r0 = recall_at_fpr(scores, labels, target_fpr=0.0)
    r_loose = recall_at_fpr(scores, labels, target_fpr=1.0)
    assert r0 < r_loose == pytest.approx(1.0)


def test_per_class_recall_breaks_down_by_real_attack_type() -> None:
    preds = [1, 0, 1, 0, 1]
    attack_types = ["PortScan", "PortScan", "BENIGN", "DDoS", "DDoS"]
    result = per_class_recall(preds, attack_types)
    assert result == {"DDoS": 0.5, "PortScan": 0.5}
    assert "BENIGN" not in result  # benign rows are never part of a recall-by-attack breakdown


def test_bootstrap_ci_brackets_the_point_estimate() -> None:
    scores = [0.9, 0.2, 0.8, 0.3, 0.7, 0.1, 0.6, 0.4, 0.95, 0.05] * 5
    labels = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0] * 5
    point = roc_auc(scores, labels)
    lo, hi = bootstrap_ci(roc_auc, scores, labels, n_resamples=300, seed=7)
    assert lo <= point <= hi


def test_bootstrap_ci_is_deterministic_for_a_fixed_seed() -> None:
    scores = [0.9, 0.2, 0.8, 0.3, 0.7, 0.1, 0.6, 0.4, 0.95, 0.05] * 3
    labels = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0] * 3
    a = bootstrap_ci(roc_auc, scores, labels, n_resamples=200, seed=11)
    b = bootstrap_ci(roc_auc, scores, labels, n_resamples=200, seed=11)
    assert a == b


def test_threshold_at_fpr_perfect_separation_finds_the_true_gap() -> None:
    scores = [0.1, 0.2, 0.3, 0.9, 0.95, 1.0]
    labels = [0, 0, 0, 1, 1, 1]
    t = threshold_at_fpr(scores, labels, target_fpr=0.0)
    assert 0.3 < t <= 0.9  # any threshold strictly between the classes works


def test_threshold_at_fpr_real_fpr_at_returned_threshold_is_within_budget() -> None:
    scores = [0.1, 0.2, 0.85, 0.9, 0.5, 1.0]
    labels = [0, 0, 0, 1, 1, 1]
    t = threshold_at_fpr(scores, labels, target_fpr=0.34)  # 1 of 3 negatives allowed
    fp = sum(1 for s, y in zip(scores, labels, strict=True) if s >= t and y == 0)
    n_neg = sum(1 for y in labels if y == 0)
    assert fp / n_neg <= 0.34 + 1e-9


def test_threshold_at_fpr_no_achievable_threshold_flags_nothing() -> None:
    # Every negative scores higher than the lowest allowed threshold could
    # tolerate -- 0.0 target FPR with ties among negatives at the top score.
    scores = [1.0, 1.0, 0.1]
    labels = [0, 1, 0]
    t = threshold_at_fpr(scores, labels, target_fpr=0.0)
    assert t > max(scores)  # nothing in the real data would ever be flagged


def test_threshold_at_fpr_no_negatives_raises() -> None:
    with pytest.raises(ValueError, match="negative"):
        threshold_at_fpr([0.1, 0.9], [1, 1], target_fpr=0.01)
