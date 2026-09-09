# Model contract — gat

Follows `docs/CONTRACTS.md §6`. Implemented by `sm_ml.graph.models.GnnNodeAnomalyModel`
(`method="gat"`, spec `sm_ml.graph.GAT_SPEC`), served by `ml-inference`.

```
model_name:                 gat
model_version:              set by ml-training at registration (semver)
task:                       node_anomaly
input_schema:               sm_ml.graph.GraphSample (feature_schema_version "1")
feature_schema_version:     "1"  (sm_ml.graph.GRAPH_FEATURE_SCHEMA_VERSION)
architecture:               GAT, hidden_dim 64, 2 layers, 4 attention heads, dropout 0.2,
                            reconstruction head
output_schema:              NodeAnomalyResult (see graphsage/CONTRACT.md)
postprocessing:             normalized_score = reconstruction_error / max(reconstruction_error in sample)
inference_latency_budget_ms: 250 (soft; no target claimed)
failure_behavior:           checkpoint missing -> GraphModelNotTrained;
                            torch / torch-geometric absent -> GraphModelUnavailable;
                            -> ml-inference MODEL_UNAVAILABLE -> structural detector only. No fabrication.
evaluation:                 recorded per ml-training run.
                            METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION
reproducibility:            SM_ML_SEED, torch + torch-geometric versions, git commit (ADR-024).
```

## Artifact layout

```
$SM_ML_GRAPH_MODEL_DIR/gat/<version>/{model.pt, metadata.json}
```

No artifact ships (ADR-024).
