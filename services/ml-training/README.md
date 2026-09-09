# ml-training

The reproducible graph-model training pipeline (Phase 8, req 12). Offline; no
service, no container.

```
dataset -> preprocessing -> graph construction -> feature generation
        -> training -> validation -> checkpoint -> model version
        -> inference -> evaluation
```

Every stage is deterministic given the seed (`TrainingConfig.seed`) and the
dataset. `config_hash()` digests the config; two runs with the same config and
dataset write byte-identical `model.json`.

## Run

```bash
python -m sm_ml_training --fixture --model-name graph_anomaly
python -m sm_ml_training --config run.json
```

`--fixture` uses `synthetic_fixture_dataset` — a small labelled toy graph. Its
validation metrics are a **plumbing check, not a benchmark claim**; the artifact
metadata records `headline_metrics: NOT VERIFIED — REQUIRES DATASET/TRAINING
EXECUTION` and `benchmark_verified: false`.

A real benchmark is loaded from `--config`'s `dataset_path` (JSON lines, one
graph per line) and carries an id + sha256. **No dataset ships in this
repository** (ADR-024).

## Model kinds

- `structural` — the always-available structural graph-anomaly detector. Training
  calibrates the z-threshold against the labelled train split (an honest
  supervised hyper-parameter fit). Runs with no optional dependency.
- `graphsage` / `gat` — need `torch` + `torch-geometric` (`sm-ml[gnn]`, not in
  CI). The training-stage boundary is implemented; without torch the pipeline
  raises `PipelineSkipped` and writes nothing.

## Artifact layout

```
<output_dir>/<model_name>/<model_version>/
    model.json      # trained parameters (a torch checkpoint for a GNN)
    metadata.json   # ModelMetadata: seed, sm-ml / torch versions, dataset id + sha256,
                    #   git commit, config hash, EvaluationReport
    stage_log.txt   # one line per pipeline stage
```

`sm_ml.graph.GraphModelRegistry` reads this layout.
