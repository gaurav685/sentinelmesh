"""Benchmark metrics — stdlib only, no numpy/sklearn (this module is what
proves a metric is real: it computes the number itself, from first
principles, rather than trusting a library's black box).

`roc_auc` is the Mann-Whitney-U form of the ROC-AUC statistic (equivalent to
the area under the ROC curve, tie-averaged) — verified against analytic
cases in tests, not assumed correct.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence

__all__ = [
    "bootstrap_ci",
    "confusion_counts",
    "per_class_recall",
    "pr_auc",
    "precision_recall_f1_fpr",
    "recall_at_fpr",
    "roc_auc",
]


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


def pr_auc(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Area under the precision-recall curve, computed by sweeping every
    distinct score value as a threshold (stdlib only, like `roc_auc` above)
    -- real average precision, not sklearn's. Undefined (raises) when there
    are no positives, same as `roc_auc`."""
    n = len(scores)
    if n != len(labels):
        raise ValueError("scores and labels must be the same length")
    n_pos = sum(1 for y in labels if y == 1)
    if n_pos == 0:
        raise ValueError("pr_auc is undefined when there are no positive labels")

    order = sorted(range(n), key=lambda i: scores[i], reverse=True)
    tp = 0
    fp = 0
    area = 0.0
    prev_recall = 0.0
    i = 0
    while i < n:
        j = i
        score_here = scores[order[i]]
        while j < n and scores[order[j]] == score_here:
            if labels[order[j]] == 1:
                tp += 1
            else:
                fp += 1
            j += 1
        recall = tp / n_pos
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        area += precision * (recall - prev_recall)
        prev_recall = recall
        i = j
    return area


def recall_at_fpr(scores: Sequence[float], labels: Sequence[int], *, target_fpr: float) -> float:
    """Recall at the lowest threshold whose real false-positive rate does
    not exceed `target_fpr` -- answers "how much do we actually catch if we
    cap false alarms at target_fpr", a real operating-point question a bare
    ROC-AUC/F1 number doesn't answer. Sweeps every distinct score value as a
    candidate threshold (no interpolation, no library), accumulating tp/fp
    incrementally in one descending pass -- O(n log n), not the naive O(n *
    distinct_scores) full rescan per threshold (found by actually running
    this against a 700K-row real test split, not just the small NSL-KDD
    fixture the original version happened to stay fast on; same sweep
    `pr_auc` above already uses). Returns 0.0 if no threshold achieves
    `target_fpr` (every row scores identically, say)."""
    n = len(scores)
    if n != len(labels):
        raise ValueError("scores and labels must be the same length")
    n_pos = sum(1 for y in labels if y == 1)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("recall_at_fpr is undefined when only one class is present")

    order = sorted(range(n), key=lambda i: scores[i], reverse=True)
    tp = 0
    fp = 0
    best_recall = 0.0
    i = 0
    while i < n:
        j = i
        score_here = scores[order[i]]
        while j < n and scores[order[j]] == score_here:
            if labels[order[j]] == 1:
                tp += 1
            else:
                fp += 1
            j += 1
        fpr = fp / n_neg
        if fpr <= target_fpr:
            best_recall = max(best_recall, tp / n_pos)
        i = j
    return round(best_recall, 6)


def per_class_recall(
    preds: Sequence[int], attack_types: Sequence[str], *, benign_label: str = "BENIGN"
) -> dict[str, float]:
    """Recall broken down by real attack-type string (never just the
    binary label) -- a model with decent overall recall can still be
    missing one entire attack category, which an aggregate number hides."""
    if len(preds) != len(attack_types):
        raise ValueError("preds and attack_types must be the same length")
    per_type: dict[str, list[int]] = {}
    for p, t in zip(preds, attack_types, strict=True):
        if t == benign_label:
            continue
        per_type.setdefault(t, []).append(p)
    return {t: round(sum(ps) / len(ps), 6) for t, ps in sorted(per_type.items())}


def bootstrap_ci(
    metric_fn: Callable[[Sequence[float], Sequence[int]], float],
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int,
) -> tuple[float, float]:
    """A real (percentile) bootstrap confidence interval: `n_resamples`
    seeded resamples-with-replacement of the real (scores, labels) pairs,
    `metric_fn` recomputed on each, the interval read off the resample
    distribution's own percentiles -- not a closed-form approximation, and
    not silently skipped when a resample happens to contain only one class
    (that resample is dropped, not allowed to crash the whole CI)."""
    n = len(scores)
    if n != len(labels):
        raise ValueError("scores and labels must be the same length")
    rng = random.Random(seed)  # noqa: S311 - a reproducible resampler, not crypto
    values: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        try:
            values.append(metric_fn([scores[i] for i in idx], [labels[i] for i in idx]))
        except ValueError:
            continue  # a resample with only one class present -- dropped, not fatal
    if not values:
        raise ValueError("every bootstrap resample had only one class present -- cannot form a CI")
    values.sort()
    alpha = (1.0 - confidence) / 2.0
    lo_idx = max(0, int(alpha * len(values)))
    hi_idx = min(len(values) - 1, int((1.0 - alpha) * len(values)))
    return round(values[lo_idx], 6), round(values[hi_idx], 6)


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
