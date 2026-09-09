# Model contract — graphsage

Follows `docs/CONTRACTS.md §6`. Implemented by `sm_ml.graph.models.GnnNodeAnomalyModel`
(`method="graphsage"`, spec `sm_ml.graph.GRAPHSAGE_SPEC`), served by `ml-inference`,
consumed by the graph-intelligence path.

```
model_name:                 graphsage
model_version:              set by ml-training at registration (semver; registry is source of truth)
task:                       node_anomaly
input_schema:               sm_ml.graph.GraphSample — node feature matrix + edge index
                            (see feature_schema_version)
feature_schema_version:     "1"  (sm_ml.graph.GRAPH_FEATURE_SCHEMA_VERSION)
architecture:               GraphSAGE, hidden_dim 64, 2 layers, mean aggregation, dropout 0.2,
                            reconstruction head (unsupervised node autoencoder)
output_schema:              NodeAnomalyResult { method, model_version, threshold,
                              scores: [{ node_id, score (>=0), normalized_score [0,1],
                                         is_anomaly, contributing_features }],
                              feature_schema_version, confidence [0,1] }
postprocessing:             normalized_score = reconstruction_error / max(reconstruction_error in sample)
inference_latency_budget_ms: 200 (soft; ml-inference emits per-model latency, no target claimed)
failure_behavior:           checkpoint missing               -> GraphModelNotTrained
                            torch / torch-geometric absent   -> GraphModelUnavailable
                            -> ml-inference returns MODEL_UNAVAILABLE
                            -> the graph-intelligence path uses sm_ml.graph.models.StructuralGraphAnomaly
                               only. No score is fabricated.
evaluation:                 dataset id + hash + metric definitions recorded per ml-training run.
                            METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION
reproducibility:            SM_ML_SEED, torch + torch-geometric versions, git commit captured
                            per training run (ADR-024).
```

## Artifact layout

```
$SM_ML_GRAPH_MODEL_DIR/graphsage/<version>/
    model.pt          # torch checkpoint (the full module, weights_only=False)
    metadata.json     # { model_version, method: "graphsage", task: "node_anomaly",
                      #   feature_schema_version, architecture spec fields,
                      #   seed, dataset_id, dataset_sha256, git_commit }
```

No artifact ships in this repository (ADR-024 — datasets and trained models stay
out). Until `ml-training` produces one, the graph-intelligence path runs on the
structural detector.
