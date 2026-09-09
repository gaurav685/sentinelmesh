# Model contract — autoencoder

Follows `docs/CONTRACTS.md §6`. Architecture specified by
`sm_ml.models.AutoencoderModel` / `AutoencoderSpec`. **Not trained.**
`score()` raises `ModelNotTrained` until `ml-training` produces weights.

Justification: for the higher-dimensional feature groups (`network_flow`,
`process_exec`) a single reconstruction error captures correlated deviations that
a per-feature MAD z-score misses. It is not justified for the low-dimensional
groups (`auth`, `file_access`) — those stay on the statistical detector.

```
model_name:                 autoencoder
model_version:              set by ml-training at registration
task:                       anomaly_score
input_schema:               sm_ml.features.FeatureSchema for one CanonicalKind (float vector)
feature_schema_version:     "1"
preprocessing_version:      "1"
architecture:               input(d) -> Linear(d,16) -> ReLU -> Linear(16,8) -> ReLU
                            -> Linear(8,16) -> ReLU -> Linear(16,d)
                            (hidden_dims strictly decreasing to the bottleneck; AutoencoderSpec)
output_schema:              { score: float (mean squared reconstruction error),
                              normalized_score: float [0,1],
                              threshold: float, is_anomaly: bool, model_version: str }
postprocessing:             threshold = p99 of the training-set reconstruction error;
                            normalized_score = clamp01(error / (threshold * k)), k = 2.0
inference_latency_budget_ms: 30 (soft; no target claimed)
failure_behavior:           no trained artifact -> ModelNotTrained -> ml-inference
                            returns MODEL_UNAVAILABLE -> detection-engine DEGRADED (ADR-013)
evaluation:                 METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION
reproducibility:            seed, PyTorch + numpy versions, git commit captured per run
```

Training (in `ml-training`, deferred): PyTorch, Adam, MSE loss, early stopping on
a held-out split; the fitted network + `threshold` + normalisation bounds are
saved as the artifact.
