from __future__ import annotations

import random

import pytest

lgb = pytest.importorskip("lightgbm")

from sm_ml.models import ModelNotTrained  # noqa: E402
from sm_ml.models.gradient_boosting import GradientBoostingModel  # noqa: E402


def _synthetic(n: int = 200, seed: int = 0) -> tuple[tuple[str, ...], list[list[float]], list[int]]:
    rng = random.Random(seed)  # noqa: S311 - a seeded test fixture generator, not crypto
    rows = [[rng.random(), rng.random(), rng.random()] for _ in range(n)]
    labels = [1 if r[0] + r[1] > 1.0 else 0 for r in rows]
    return ("a", "b", "c"), rows, labels


def test_fit_separates_a_real_decision_boundary() -> None:
    names, rows, labels = _synthetic()
    model = GradientBoostingModel.fit(names, rows, labels, seed=42, model_version="t")
    high = model.score([0.95, 0.95, 0.05])
    low = model.score([0.02, 0.02, 0.02])
    assert high.is_anomaly
    assert not low.is_anomaly
    assert high.score > low.score


def test_fit_requires_both_classes() -> None:
    names = ("a", "b", "c")
    with pytest.raises(ValueError, match="both classes"):
        GradientBoostingModel.fit(names, [[0.1, 0.1, 0.1]] * 10, [0] * 10, seed=1, model_version="t")


def test_score_before_fit_or_load_raises() -> None:
    model = GradientBoostingModel()
    with pytest.raises(ModelNotTrained):
        model.score([0.1, 0.1, 0.1])


def test_save_load_round_trip_matches(tmp_path) -> None:  # type: ignore[no-untyped-def]
    names, rows, labels = _synthetic()
    model = GradientBoostingModel.fit(names, rows, labels, seed=42, model_version="v1")
    before = model.score([0.9, 0.9, 0.1])

    model.save(tmp_path)
    loaded = GradientBoostingModel.load(tmp_path)
    after = loaded.score([0.9, 0.9, 0.1])

    assert abs(before.score - after.score) < 1e-9
    assert loaded.model_version == "v1"
    assert loaded.feature_names == names


def test_wrong_feature_count_rejected() -> None:
    names, rows, labels = _synthetic()
    model = GradientBoostingModel.fit(names, rows, labels, seed=42, model_version="t")
    with pytest.raises(ValueError, match="expected 3 features"):
        model.score([0.1, 0.2])
