from __future__ import annotations

import pytest

from sm_contracts import AnomalyMethod
from sm_ml import Preprocessor, StatisticalModel
from sm_ml.models import AutoencoderModel, AutoencoderSpec, ModelNotTrained

_NAMES = ("a", "b", "c")


# ---- preprocessing -------------------------------------------------------
def test_preprocessor_standardises() -> None:
    rows = [[0.0, 10.0, 5.0], [2.0, 10.0, 7.0], [4.0, 10.0, 9.0]]
    pre = Preprocessor.fit(_NAMES, rows)
    out = pre.transform([2.0, 10.0, 7.0])
    assert out[0] == pytest.approx(0.0)     # mean of a
    assert out[1] == pytest.approx(0.0)     # constant feature b -> std 1 -> 0
    assert out[2] == pytest.approx(0.0)


def test_preprocessor_roundtrips() -> None:
    pre = Preprocessor.fit(_NAMES, [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    assert Preprocessor.from_dict(pre.to_dict()) == pre


def test_preprocessor_rejects_wrong_width() -> None:
    pre = Preprocessor.fit(_NAMES, [[1.0, 2.0, 3.0]])
    with pytest.raises(ValueError, match="expected 3"):
        pre.transform([1.0, 2.0])


# ---- statistical model -------------------------------------------------
def _fit_normal() -> StatisticalModel:
    rows = [[float(i % 3), 100.0 + i, 1.0] for i in range(60)]
    return StatisticalModel.fit(_NAMES, rows, z_threshold=3.5)


def test_statistical_flags_a_clear_outlier() -> None:
    model = _fit_normal()
    normal = model.score([1.0, 130.0, 1.0])
    assert not normal.is_anomaly
    assert normal.normalized_score < 0.5

    outlier = model.score([1.0, 5000.0, 1.0])
    assert outlier.is_anomaly
    assert outlier.method is AnomalyMethod.mad_zscore
    assert outlier.normalized_score > 0.5
    assert "b" in outlier.contributing_features


def test_statistical_constant_feature_never_fires() -> None:
    model = _fit_normal()
    s = model.score([1.0, 130.0, 999.0])  # feature c was constant in training
    assert "c" not in s.contributing_features


def test_statistical_is_deterministic_and_serialisable() -> None:
    model = _fit_normal()
    a = model.score([2.0, 4000.0, 1.0])
    b = StatisticalModel.from_dict(model.to_dict()).score([2.0, 4000.0, 1.0])
    assert a == b


def test_statistical_rejects_wrong_feature_count() -> None:
    with pytest.raises(ValueError, match="expected 3"):
        _fit_normal().score([1.0, 2.0])


# ---- autoencoder (spec only, not trained) ----------------------------
def test_autoencoder_spec_requires_decreasing_bottleneck() -> None:
    AutoencoderSpec(input_dim=8, hidden_dims=(16, 8))  # ok
    with pytest.raises(ValueError, match="decreasing"):
        AutoencoderSpec(input_dim=8, hidden_dims=(8, 16))


def test_autoencoder_score_is_not_trained() -> None:
    model = AutoencoderModel(AutoencoderSpec(input_dim=8))
    with pytest.raises(ModelNotTrained):
        model.score([0.0] * 8)


def test_autoencoder_build_module_trains_and_round_trips(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A real train -> save -> load -> score round trip, skipped where torch
    (`sm-ml[autoencoder]`) is absent -- never a fabricated pass."""
    torch = pytest.importorskip("torch")
    from sm_ml.models.autoencoder import build_module

    spec = AutoencoderSpec(input_dim=4, hidden_dims=(3, 2))
    module = build_module(spec)
    x = torch.zeros((5, 4), dtype=torch.float32)
    optimizer = torch.optim.Adam(module.parameters(), lr=0.1)
    for _ in range(20):
        optimizer.zero_grad()
        loss = torch.mean((module(x) - x) ** 2)
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        final_error = float(torch.mean((module(x) - x) ** 2).item())
    assert final_error < 0.01  # a real, measured post-training reconstruction error

    out_dir = tmp_path / "autoencoder_test"
    out_dir.mkdir()
    torch.save(module, out_dir / "model.pt")
    import json

    (out_dir / "metadata.json").write_text(
        json.dumps(
            {
                "model_version": "test-v1", "input_dim": 4, "hidden_dims": [3, 2],
                "error_quantile": 0.99, "normalisation_k": 2.0,
                "feature_names": ["a", "b", "c", "d"], "error_threshold": 0.05,
            }
        ),
        encoding="utf-8",
    )
    loaded = AutoencoderModel.load(out_dir)
    score = loaded.score([0.0, 0.0, 0.0, 0.0])
    assert score.score < 0.05
    assert not score.is_anomaly
    assert score.model_version == "test-v1"
