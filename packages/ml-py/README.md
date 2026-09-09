# sm-ml

The SentinelMesh ML layer.

- **`sm_ml.features`** — a versioned `FeatureSchema` per `CanonicalKind` and
  deterministic, dependency-free extractors: `extract_features(canonical) ->
  FeatureVector`. Same event in → same vector out, always.
- **`sm_ml.preprocessing`** — `Preprocessor` (fit / transform, versioned,
  serializable). Pure-Python standardisation; no numpy.
- **`sm_ml.models`** — the `AnomalyModel` protocol + `AnomalyScore`. `StatisticalModel`
  (robust MAD z-score) needs only the standard library and is the always-available
  detector / ADR-013 degraded path. `IsolationForestModel` (scikit-learn) and the
  `AutoencoderModel` architecture spec need `sm-ml[serving]` and a trained
  artifact; without one they raise `ModelUnavailable` / `ModelNotTrained`.
- **`sm_ml.registry`** — `ModelRegistry` loads trained artifacts from
  `SM_ML_MODEL_DIR`. Missing directory = empty registry (callers degrade).

No accuracy, F1, ROC-AUC, precision, recall, latency or throughput number
appears anywhere in this package or its model contracts. Those require a real
training / evaluation run — see `ml/models/*/CONTRACT.md` (marked
`NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`) and ADR-024.
