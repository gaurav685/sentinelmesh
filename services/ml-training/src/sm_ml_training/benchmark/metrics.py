"""Benchmark metrics — stdlib only, no numpy/sklearn (this module is what
proves a metric is real: it computes the number itself, from first
principles, rather than trusting a library's black box).

`roc_auc` is the Mann-Whitney-U form of the ROC-AUC statistic (equivalent to
the area under the ROC curve, tie-averaged) — verified against analytic
cases in tests, not assumed correct.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["confusion_counts", "precision_recall_f1_fpr", "roc_auc"]


def roc_auc(scores: Sequence[float], labels: Sequence[int]) -> float:
    n = len(scores)
    if n != len(labels):
        raise ValueError("scores and labels must be the same length")
    n_pos = sum(1 for y in labels if y == 1)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("roc_auc is undefined when only one class is present")

    order = sorted(range(n), key=lambda i: scores[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg_rank = ((i + 1) + (j + 1)) / 2.0  # 1-indexed, tie-averaged
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1

    sum_ranks_pos = sum(ranks[i] for i in range(n) if labels[i] == 1)
    return (sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def confusion_counts(preds: Sequence[int], labels: Sequence[int]) -> dict[str, int]:
    if len(preds) != len(labels):
        raise ValueError("preds and labels must be the same length")
    tp = sum(1 for p, y in zip(preds, labels, strict=True) if p == 1 and y == 1)
    fp = sum(1 for p, y in zip(preds, labels, strict=True) if p == 1 and y == 0)
    tn = sum(1 for p, y in zip(preds, labels, strict=True) if p == 0 and y == 0)
    fn = sum(1 for p, y in zip(preds, labels, strict=True) if p == 0 and y == 1)
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def precision_recall_f1_fpr(preds: Sequence[int], labels: Sequence[int]) -> dict[str, float]:
    c = confusion_counts(preds, labels)
    tp, fp, tn, fn = c["tp"], c["fp"], c["tn"], c["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "false_positive_rate": round(fpr, 6),
    }
