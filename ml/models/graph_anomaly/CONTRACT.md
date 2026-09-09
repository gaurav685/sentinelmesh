# Model contract — graph_anomaly

Follows `docs/CONTRACTS.md §6`. This is the **always-available** graph anomaly
detector: `sm_ml.graph.models.StructuralGraphAnomaly` (standard library, no
optional dependency). It is the ADR-013 degraded path for the graph-intelligence
layer *and* a first-class detector.

```
model_name:                 graph_anomaly (structural)
model_version:              null — no trained weights; the method is fixed code
task:                       node_anomaly
input_schema:               sm_ml.graph.GraphSample (feature_schema_version "1")
method:                     structural_zscore — robust MAD z-score over the node's
                            structural feature vector; score = max |z| over features
output_schema:              NodeAnomalyResult (see graphsage/CONTRACT.md)
postprocessing:             normalized_score = logistic(max_z - z_threshold); crosses 0.5 at the verdict
threshold:                  z_threshold, default 3.5 (SM_GRAPH_ANOMALY_Z)
inference_latency_budget_ms: 20 (soft)
failure_behavior:           none — always available; a graph with one node yields all-zero scores
evaluation:                 no dataset needed to run; there is still no accuracy claim.
                            METRICS: NOT VERIFIED — REQUIRES DATASET/EVALUATION EXECUTION
reproducibility:            pure function of the GraphSample — deterministic, no seed, no RNG
```

Companion heuristics in the same module: `SuspiciousSubgraphHeuristic`
(suspicious-subgraph verdict), `ConnectedComponentClusterer` /
`LabelPropagationClusterer` (threat-cluster discovery) — all standard-library and
deterministic, all `confidence = 0.0` until an evaluation run calibrates them.

No artifact. No accuracy figure.
