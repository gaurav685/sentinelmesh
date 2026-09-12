from __future__ import annotations

import pytest
from sm_ml_training.benchmark.metrics import confusion_counts, precision_recall_f1_fpr, roc_auc


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
