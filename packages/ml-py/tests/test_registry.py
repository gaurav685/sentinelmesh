from __future__ import annotations

import json
from pathlib import Path

import pytest

from sm_ml import ModelRegistry, StatisticalModel
from sm_ml.models import ModelUnavailable


def test_missing_directory_is_an_empty_registry(tmp_path: Path) -> None:
    reg = ModelRegistry(tmp_path / "does-not-exist")
    assert reg.available() == []
    with pytest.raises(ModelUnavailable):
        reg.load("isolation_forest")


def test_loads_a_statistical_artifact(tmp_path: Path) -> None:
    model = StatisticalModel.fit(("x", "y"), [[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]])
    vdir = tmp_path / "baseline" / "0.1.0"
    vdir.mkdir(parents=True)
    (vdir / "model.json").write_text(json.dumps(model.to_dict()), encoding="utf-8")
    (vdir / "metadata.json").write_text(
        json.dumps({
            "model_version": "0.1.0", "method": "mad_zscore",
            "task": "anomaly_score", "feature_schema_version": "1",
        }),
        encoding="utf-8",
    )
    reg = ModelRegistry(tmp_path)
    refs = reg.available()
    assert [r.name for r in refs] == ["baseline"]
    loaded = reg.load("baseline")
    assert isinstance(loaded, StatisticalModel)
    assert loaded.score([0.0, 1.0]) == model.score([0.0, 1.0])


def test_isolation_forest_metadata_without_artifact_is_unavailable(tmp_path: Path) -> None:
    vdir = tmp_path / "isolation_forest" / "0.1.0"
    vdir.mkdir(parents=True)
    (vdir / "metadata.json").write_text(
        json.dumps({"model_version": "0.1.0", "method": "isolation_forest"}), encoding="utf-8"
    )
    reg = ModelRegistry(tmp_path)
    assert [r.name for r in reg.available()] == ["isolation_forest"]
    with pytest.raises(ModelUnavailable):
        reg.load("isolation_forest")


def test_from_env_uses_the_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SM_ML_MODEL_DIR", str(tmp_path))
    reg = ModelRegistry.from_env()
    assert reg.available() == []
