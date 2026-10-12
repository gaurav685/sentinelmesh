# Model card: `gradient_boosting_network_flow`

## Summary

LightGBM binary classifier, trained on real NSL-KDD traffic through this platform's own
real production feature extraction (`sm_ml.features.extract_features`, the same function
`detection-engine` calls at inference time). Serves the real `NetworkFlowPayload` 8-dim
feature schema (`feature_schema_version=1`) -- the identical input `isolation_forest_network_flow`
and `autoencoder_network_flow` already use, train/serve parity is structural, not just intended.

**Behind a feature flag, off by default.** `sm_ml.registry.ModelRegistry` excludes any
`gradient_boosting`-method artifact from its catalog unless `SM_ML_ENABLE_GRADIENT_BOOSTING`
is set to a truthy value (`1`/`true`/`yes`/`on`). With the flag off, `ml-inference` behaves
exactly as it did before this model existed; `isolation_forest_network_flow` remains the
real fallback `detection-engine` degrades to when a model is unavailable (ADR-013) --
no new fallback code was needed, since that degrade path already exists.

## Real difference from the platform's other two network-flow models

| | `isolation_forest_network_flow` | `autoencoder_network_flow` | `gradient_boosting_network_flow` |
|---|---|---|---|
| Learning type | Unsupervised | Unsupervised | **Supervised** |
| Fit on real labels? | No (benign-only) | No (benign-only) | **Yes** (NSL-KDD normal/attack) |
| Threshold | Train-score percentile | Train-error quantile | Fixed decision probability (default 0.5) |

Being supervised is a real, structural difference, not a detail: this model learns directly
from NSL-KDD's real label, where the other two never see a label during fitting. Its real
measured numbers below should not be read as a like-for-like unsupervised comparison.

## Real measured performance (held-out NSL-KDD test, `KDDTest+.txt`, 22,544 rows)

Produced by `scripts/train_gradient_boosting_network_flow.py --eval-file`:

| | |
|---|---|
| tp / fp / fn / tn | 9134 / 392 / 3699 / 9319 |
| Precision | 0.959 |
| Recall | 0.712 |
| Status | VERIFIED (real run, this session) |

For comparison, the real existing numbers in `docs/ML_BENCHMARK_REPORT.md` for the other two
production models on the same held-out file: `isolation_forest_network_flow` precision 0.961 /
recall 0.621 (NSL-KDD 125-dim benchmark encoding, a different harness, not the 8-dim production
encoding directly) and `autoencoder_network_flow`'s own 8-dim held-out check, precision 0.845 /
recall 0.100. This model's real recall (0.712) at a comparable precision is the strongest of the
three measured on this specific held-out file at the real 8-dim production schema -- but it is the
only supervised one, so this is not a clean apples-to-apples claim.

## Live-detection readiness — **offline benchmark only, not wired into live scoring**

Checked directly against the real code, not assumed either way:

1. **`detection-engine` never requests this model, flag or no flag.**
   `services/detection-engine/src/sm_detection_engine/inference_client.py`'s
   `MODEL_FOR_KIND` hardcodes `CanonicalKind.network_flow -> "isolation_forest_network_flow"`.
   Turning `SM_ML_ENABLE_GRADIENT_BOOSTING` on only makes `ml-inference` willing to
   *serve* `/infer/gradient_boosting_network_flow` if something calls it directly (which
   is what this session's own benchmark scripts do) — it does **not** make the real
   detection flow call it. Wiring that in (adding a second model lookup, or an ensemble
   path, in `inference_client.py`/the detection handler) is real, separate work, not done
   here.
2. **No real external network-flow collector runs in this repo.** `services/ingestion-gateway`'s
   `POST /api/v1/ingest/network_flow` validates a full `NetworkFlowPayload` (all 8 of this
   model's real feature inputs have a schema field), so a real sensor/collector sending complete
   flow records *would* produce full real features through `normalization-engine`'s `_network_flow`
   mapper — but no such collector is built or deployed in this project; it is a real but unused
   capability.
3. **The only producer that actually runs end-to-end, `services/simulation-service`, populates a
   degenerate subset.** Real feature-mapping table, checked against
   `sm_simulation_service/pipeline.py`'s `_to_payload` and `sm_ml.features.extract.extract_features`:

   | Model feature | `NetworkFlowPayload` field | How it's computed | Simulation-service reality |
   |---|---|---|---|
   | `bytes_sent_log` | `bytes_sent` | `ln1p(bytes_sent)` | Real only on the APT scenario's exfil step (`attributes["bytes"]`); **0 on every other step** |
   | `bytes_received_log` | `bytes_received` | `ln1p(bytes_received)` | **Never set — always 0** |
   | `packets_total_log` | `packets_sent`+`packets_received` | `ln1p(sum)` | **Never set — always 0** |
   | `dst_port` | `dst_port` | passthrough | **Never set (`None`→0) — always 0** |
   | `dst_port_is_system` | `dst_port` | `0<dst_port<1024` | **Always 0** (depends on the always-0 `dst_port`) |
   | `dst_port_is_ephemeral` | `dst_port` | `dst_port>=49152` | **Always 0** |
   | `proto_tcp` | `protocol` | `protocol=="tcp"` | Hardcoded `protocol="tcp"` — **always 1.0, no real variance** |
   | `direction_outbound` | `direction` | `direction=="outbound"` | Real-ish: `outbound` or `lateral` only (never `inbound`/`unknown`) |

   **6 of 8 real feature dimensions are degenerate constants (always 0 or always 1) for every
   event this repo's own simulation pipeline actually produces.** Only `bytes_sent_log` and
   `direction_outbound` carry any real variation, and even `bytes_sent_log` is non-zero only on
   one scenario step. This is a materially worse gap than the training-time NSL-KDD limitation
   below (which zeroes 5 of 8 dims) — simulated live traffic zeroes 6.

**Conclusion, per the project's non-fabrication rule: this model is an offline benchmark result
only.** `SM_ML_ENABLE_GRADIENT_BOOSTING` stays off by default and should stay off until both (1)
`detection-engine` is actually wired to request this model, and (2) a real collector or a richer
simulation payload supplies real values for the 6 currently-degenerate feature dimensions. Flipping
the flag today would not produce fabricated scores (ADR-013's degrade path and the schema/version
checks still hold), but it also would not produce live detection value beyond what a model fed six
constant zeros can show — closer to a constant-input probe of this model than a real evaluation.

## Known limitations (real, not glossed over)

- NSL-KDD provides no destination port, packet counts, or traffic direction. 5 of this
  schema's 8 real feature dimensions (`dst_port`, `dst_port_is_system`, `dst_port_is_ephemeral`,
  `packets_total_log`, `direction_outbound`) are therefore constant zero in training and at
  inference time for data replayed from it -- identical limitation to the other two models,
  not unique to this one.
- Trained on 1999-era NSL-KDD traffic. No claim is made about performance on real modern
  traffic; see `docs/ML_BENCHMARK_REPORT.md`'s Phase 1/1.5/1.6 sections for this project's
  separate, real CICIDS2017/UNSW-NB15 evaluation (a different feature schema, not served here).
- Fixed 0.5 decision threshold (`--threshold` at training time), not validation-calibrated at
  a target false-positive rate the way the Phase 1.5/1.6 benchmark models are.

## Input schema validation

Served through the same generic `/infer/{model}` endpoint (`services/ml-inference`) every
other registry model uses -- `req.feature_schema_version` is checked against the server's real
`FEATURE_SCHEMA_VERSION`, and `len(req.features)` against `schema_for(req.kind).names`'s real
expected count, before the model is ever called. No new validation code was needed; this model
uses the same `AnomalyModel.score()` interface shape as the other two.

## Reproducing this artifact

```
python scripts/train_gradient_boosting_network_flow.py \
    --train-file <path to KDDTrain+.txt> \
    --eval-file <path to KDDTest+.txt> \
    --out ml/artifacts/gradient_boosting_network_flow/v1
```

The model binary (`model.txt`, LightGBM's own text format) is git-ignored, same convention as
`*.joblib`/`*.pt` for the other two models -- reproduce it with the command above, don't expect
it checked in. `metadata.json` (real training provenance, feature names, measured limitations)
is committed.
