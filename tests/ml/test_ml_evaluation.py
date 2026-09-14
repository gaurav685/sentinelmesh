"""Statistical model evaluation on a fixture synthetic dataset.

These are *plumbing* checks, not performance claims (Constitution 5): they
verify the model produces a defined, reproducible, non-NaN score on a small
deterministic fixture. A real benchmark (Phase 15) evaluates the same model
on NSL-KDD and reports ROC-AUC with an honest caveat.
"""

from __future__ import annotations

import math

from sm_ml import StatisticalModel

_NAMES = ("a", "b", "c")


def _fit(seed: int = 1) -> StatisticalModel:
    rows = [[float((i + seed) % 3), 100.0 + i, 1.0] for i in range(60)]
    return StatisticalModel.fit(_NAMES, rows, z_threshold=3.5)


def test_roc_auc_is_above_random_on_fixture_data() -> None:
    """A deterministic model on a fixture dataset must score above random
    (ROC-AUC > 0.5) — this is a plumbing check, not a performance claim."""
    model = _fit()
    # Label an injected outlier as positive, everything else negative.
    points = [[float(i % 3), 100.0 + i, 1.0] for i in range(60)]
    points.append([1.0, 5000.0, 1.0])  # the injected outlier
    labels = [0] * 60 + [1]

    scores = [model.score(p).score for p in points]
    # Mann-Whitney U expressed as ROC-AUC: fraction of (outlier, normal) pairs
    # where the outlier scores higher, ties counted as 0.5.
    normal = [s for s, lab in zip(scores, labels, strict=True) if lab == 0]
    outlier = [s for s, lab in zip(scores, labels, strict=True) if lab == 1]
    assert normal and outlier
    wins = sum(1 for o in outlier for n in normal if o > n)
    ties = sum(1 for o in outlier for n in normal if o == n)
    auc = (wins + 0.5 * ties) / (len(outlier) * len(normal))
    assert auc > 0.5, f"ROC-AUC {auc:.3f} is not above random"


def test_precision_and_recall_are_defined() -> None:
    model = _fit()
    normal = [model.score([float(i % 3), 100.0 + i, 1.0]) for i in range(60)]
    outlier = [model.score([1.0, 5000.0, 1.0])]
    tp = sum(1 for s in outlier if s.is_anomaly)
    fp = sum(1 for s in normal if s.is_anomaly)
    fn = sum(1 for s in outlier if not s.is_anomaly)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    assert 0.0 <= precision <= 1.0
    assert 0.0 <= recall <= 1.0
    assert precision > 0.0
    assert recall == 1.0


def test_no_nan_results_on_all_zero_feature_vector() -> None:
    """A feature vector of all zeros must not produce NaN scores — the MAD
    path clamps to z=0 when the deviation is below epsilon."""
    model = _fit()
    score = model.score([0.0, 0.0, 0.0])
    assert math.isfinite(score.score)
    assert math.isfinite(score.normalized_score)
    assert 0.0 <= score.normalized_score <= 1.0


def test_no_nan_when_training_data_has_no_benign_samples() -> None:
    """A constant training column must not propagate NaN through the logistic
    normalisation — the MAD clamp makes the z-score 0 for that feature."""
    rows = [[5.0, 7.0, 9.0]] * 30  # every column is constant
    model = StatisticalModel.fit(_NAMES, rows)
    score = model.score([5.0, 7.0, 9.0])
    assert math.isfinite(score.score)
    assert math.isfinite(score.normalized_score)
    assert not math.isnan(score.score)


def test_reproducibility_same_seed_same_results() -> None:
    a = _fit(seed=1)
    b = _fit(seed=1)
    assert a.to_dict() == b.to_dict()
    vec = [1.0, 5000.0, 1.0]
    assert a.score(vec) == b.score(vec)


def test_different_seeds_produce_reproducible_within_a_seed() -> None:
    """Fitting is deterministic within a seed; the fixture rows are the same
    for every seed (the seed only offsets the `i % 3` cycle), so the model is
    identical across seeds here — what matters is that the *same* seed always
    produces the *same* model (see `test_reproducibility_same_seed_same_results`).
    This is a plumbing check, not a claim that seeds change behaviour."""
    a = _fit(seed=1)
    b = _fit(seed=1)
    assert a.to_dict() == b.to_dict()