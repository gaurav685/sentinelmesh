from __future__ import annotations

import json

import pytest
from sm_ml_training import (
    ModelKind,
    PipelineSkipped,
    TrainingConfig,
    TrainingPipeline,
    synthetic_fixture_dataset,
    write_artifact,
)

from sm_ml.graph import GraphModelRegistry


def _cfg(**over: object) -> TrainingConfig:
    base: dict[str, object] = dict(model_name="graph_anomaly", model_kind=ModelKind.structural, seed=1337)
    base.update(over)
    return TrainingConfig(**base)  # type: ignore[arg-type]


# ---- dataset -------------------------------------------------------
def test_fixture_dataset_is_deterministic() -> None:
    a = synthetic_fixture_dataset(1337)
    b = synthetic_fixture_dataset(1337)
    assert a.sha256 == b.sha256
    assert a.dataset_id == b.dataset_id
    assert a.num_anomalous_nodes == a.num_samples  # one injected hub per sample
    assert synthetic_fixture_dataset(7).sha256 != a.sha256


# ---- pipeline runs all ten stages ------------------------------
def test_pipeline_runs_end_to_end_on_the_fixture() -> None:
    result = TrainingPipeline(_cfg()).run()
    stages = {line.split(":", 1)[0] for line in result.stage_log}
    assert stages >= {
        "dataset", "preprocessing", "graph_construction", "feature_generation", "training",
        "validation", "checkpoint", "model_version", "inference", "evaluation",
    }
    assert result.trained.method == "structural_zscore"
    assert result.metadata.evaluation.headline_metrics.startswith("NOT VERIFIED")
    assert result.metadata.evaluation.benchmark_verified is False
    assert result.metadata.feature_schema_version == "1"


def test_two_runs_with_the_same_config_are_identical() -> None:
    a = TrainingPipeline(_cfg()).run()
    b = TrainingPipeline(_cfg()).run()
    assert a.model_version == b.model_version
    assert a.trained == b.trained
    assert a.metadata.config_hash == b.metadata.config_hash
    assert a.metadata.dataset_sha256 == b.metadata.dataset_sha256


def test_config_hash_changes_with_a_meaningful_knob_not_with_output_dir() -> None:
    assert _cfg(output_dir="/a").config_hash() == _cfg(output_dir="/b").config_hash()
    assert _cfg(seed=1).config_hash() != _cfg(seed=2).config_hash()


# ---- failure isolation: no torch -> skip, no artifact --------
def test_gnn_kind_is_skipped_without_torch() -> None:
    try:
        import torch  # noqa: F401
    except ImportError:
        with pytest.raises(PipelineSkipped):
            TrainingPipeline(_cfg(model_kind=ModelKind.graphsage)).run()
    else:  # pragma: no cover - torch not installed in CI
        pytest.skip("torch is installed")


def test_benchmark_kind_without_a_path_is_skipped() -> None:
    from sm_ml_training import DatasetKind

    with pytest.raises(PipelineSkipped):
        TrainingPipeline(_cfg(dataset_kind=DatasetKind.benchmark)).run()


# ---- artifact handling + registry round-trip -----------------
def test_artifact_is_written_and_loadable_by_the_registry(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = TrainingPipeline(_cfg(output_dir=str(tmp_path))).run()
    dest = write_artifact(result, tmp_path)
    assert (dest / "model.json").exists()
    assert (dest / "metadata.json").exists()
    assert (dest / "stage_log.txt").exists()

    meta = json.loads((dest / "metadata.json").read_text(encoding="utf-8"))
    assert meta["model_version"] == result.model_version
    assert meta["evaluation"]["headline_metrics"].startswith("NOT VERIFIED")

    loaded = GraphModelRegistry(tmp_path).load("graph_anomaly")
    scored = loaded.score_nodes(synthetic_fixture_dataset(1337).samples[0].sample)
    assert len(scored.scores) > 0
    assert loaded.model_version == result.model_version
