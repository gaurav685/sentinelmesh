# Model contract — isolation_forest

Follows `docs/CONTRACTS.md §6`. Implemented by `sm_ml.models.IsolationForestModel`,
served by `ml-inference`, consumed by `detection-engine`.

```
model_name:                 isolation_forest
model_version:              set by ml-training at registration (semver; registry is source of truth)
task:                       anomaly_score
input_schema:               sm_ml.features.FeatureSchema for one CanonicalKind
                            (ordered float vector; see feature_schema_version)
feature_schema_version:     "1"  (sm_ml.FEATURE_SCHEMA_VERSION)
preprocessing_version:      "1"  (sm_ml.PREPROCESSING_VERSION — StandardScaler-style)
output_schema:              { score: float (>=0, higher = more anomalous),
                              normalized_score: float [0,1],
                              threshold: float,
                              is_anomaly: bool,
                              model_version: str,
                              contributing_features: [] }
postprocessing:             normalized_score = clamp01((score - score_min) / (score_max - score_min))
                            with score_min / score_max from the training set (metadata.json)
inference_latency_budget_ms: 50 (soft; ml-inference emits per-model latency, no target claimed)
failure_behavior:           artifact missing OR numpy/scikit-learn absent -> ModelUnavailable
                            -> ml-inference returns MODEL_UNAVAILABLE
                            -> detection-engine sets scoring_status = DEGRADED and uses the
                               statistical detector only (ADR-013). No score is fabricated.
evaluation:                 dataset id + hash + metric definitions recorded per ml-training run.
                            METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION
reproducibility:            random_state, scikit-learn + numpy versions, git commit captured
                            per training run (ADR-024).
```

## Artifact layout

```
$SM_ML_MODEL_DIR/isolation_forest/<version>/
    model.joblib      # fitted sklearn.ensemble.IsolationForest
    metadata.json     # { model_version, method: "isolation_forest", task,
                      #   feature_schema_version, feature_names,
                      #   score_min, score_max, threshold }
```

No artifact ships in this repository (ADR-024 — datasets and trained models stay
out). Until `ml-training` produces one, `ml-inference` reports the model as
unavailable and the pipeline runs on the statistical detector.
