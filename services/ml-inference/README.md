# ml-inference

Model serving (ADR-013). Loads registered anomaly models in-process and serves
typed inference to `detection-engine`.

## Endpoints (internal, service-JWT, audience `ml-inference`)

- `GET  /api/v1/models` — the registered model catalog.
- `POST /api/v1/infer/{model}` — body `{kind, feature_schema_version, features:
  [float]}`; response is the `AnomalyScore` shape (`method`, `score`,
  `normalized_score` ∈ [0,1], `threshold`, `is_anomaly`, `model_version`,
  `contributing_features`).
- `GET /healthz` `/readyz` `/api/v1/meta` `/metrics`. Port 8005.

## Failure behaviour

A model that is not registered, cannot be loaded, or whose serving dependencies
(`sm-ml[serving]` — numpy + scikit-learn) are missing → **HTTP 503**
`dependency_unavailable` with `MODEL_UNAVAILABLE: <model>` and a `model` detail.
An inference exception maps to the same. `detection-engine` treats that as
`scoring_status = DEGRADED` and uses the statistical detector only. Never a 500,
never a fabricated score.

## Models

Loaded from `SM_ML_MODEL_DIR` (`sm_ml.ModelRegistry`). This repository ships **no
trained artifacts** (ADR-024) — until `ml-training` produces one, every `infer`
call returns `MODEL_UNAVAILABLE` and the pipeline runs on the statistical
detector. Statistical-model artifacts (`model.json`) serve with the base install;
Isolation Forest (`model.joblib`) needs the `serving` extra.

## Run

```bash
python -m sm_ml_inference
```
