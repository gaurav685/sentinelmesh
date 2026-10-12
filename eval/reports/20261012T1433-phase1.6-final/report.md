# Phase 1.6 benchmark run `20261012T1433-phase1.6-final`

Commit `ee95b5a11f7e` (LightGBM production integration, UNSW-NB15 orientation fix) plus this
session's corrected-CICIDS2017 (WTMC-2021) rerun and a live-detection feature-compatibility
audit, consolidated into this one run-id.
Full machine-readable detail in this directory: `unsw_nb15_official_audit.json`,
`inference_latency_benchmark.json`, `inference_latency_e2e_benchmark.json`,
`partial_cicids2017_corrected.json`. Full real tables, methodology, and honest discussion:
`docs/ML_BENCHMARK_REPORT.md`'s "Phase 1.6" section; the feature-compatibility table:
`docs/models/gradient_boosting_network_flow.md`.

This run answers the user's Phase 1.6 requests directly: split orientation, duplicate
sensitivity, base rates, making the corrected CICIDS2017 release primary with per-attack
recall, real end-to-end API latency (not just in-process), and whether SentinelMesh's live
pipelines actually feed this model real features (they do not, documented plainly below).

## Headline, real, measured

- **UNSW-NB15's official mirror files are reversed vs. their own filenames.** The documented
  convention is 175,341 train / 82,332 test; this mirror's `training-set.csv` physically has
  82,332 rows and `testing-set.csv` has 175,341. `load_unsw_nb15_official_split` now defaults to
  `orientation="standard"` (picks by real row count, not filename) as the primary result
  everywhere in this report; the old reversed behaviour (`orientation="literal"`) is kept only as
  a labelled secondary comparison.
- **Exact-duplicate test rows checked, not ignored.** 1,295 of the standard-orientation test
  split's 53,939 unique rows (2.40%) are exact-duplicate feature vectors of a train row. The
  primary result keeps them in (the official split, as shipped); a labelled secondary rerun with
  them removed changes LightGBM ROC-AUC by only −0.0024 (0.985255 → 0.982895) — a real, small
  sensitivity, not a correction applied to the primary number.
- **Attack prevalence reported next to every test set's PR-AUC** (0.22–0.68 depending on
  split) — every PR-AUC number elsewhere in this report is well clear of its own no-skill
  baseline, so none of them are an artefact of a near-100%-positive test set.
- **Corrected CICIDS2017 (WTMC-2021) downloaded, run for real, and promoted to primary** —
  the Kaggle mirror's original-label numbers are now the labelled secondary comparison.
  LightGBM's day-split (unseen-attack) ROC-AUC improves substantially on the corrected labels:
  0.753472 → 0.953734, consistent with the corrected release's own claim of fixing >20%
  mislabelled flows. Per-attack recall on the held-out Friday day: DDoS recall is strong for
  Isolation Forest/LightGBM (0.999/0.942), but PortScan and the corrected release's new
  `"Bot - Attempted"` label are missed by every model (recall ≈ 0 for both).
- **LightGBM is served by `ml-inference` behind a flag, but is NOT wired into live detection and
  is NOT fed real live features — checked directly, not assumed.** `detection-engine`'s
  `MODEL_FOR_KIND` never requests this model regardless of the flag; `services/simulation-service`,
  the only real end-to-end event producer in this repo, leaves 6 of the model's 8 feature
  dimensions as constant 0 or 1 for every event it generates. Documented as an **offline
  benchmark result only** in `docs/models/gradient_boosting_network_flow.md`; the flag stays off.
- **Two different latency numbers, not interchangeable.** In-process (`model.score()` /
  `Booster.predict()` directly, bypassing the FastAPI app): single-request p50 0.147 ms
  (6,090.5 flows/s), vectorised batch-of-1000 p50 2.43 ms (411,234.9 flows/s). Real end-to-end
  through the actual `/infer` API (real routing/auth/validation/scoring, in-process ASGI
  transport — no real network socket): single-request p50 3.64 ms (269.5 req/s); "batch" is
  1,000 real sequential HTTP calls (no batch endpoint exists), p50 3.60 ms (272.0 req/s) — the
  ~67x in-process batching speedup does not exist for the real API because there is nothing to
  batch into.
- **The known-attack-vs-unseen-attack generalisation gap holds on every dataset tested.**
  LightGBM is near-perfect recognising attack types it saw in training (ROC-AUC up to 0.999983)
  but drops to 0.75–0.95 the moment the split holds out an attack type or capture day it never
  trained on — the real, central weakness this phase's evaluation keeps surfacing.

## Not yet done

Phase 2 (DARPA TC) was explicitly out of scope for this phase, per the user's instruction. Wiring
`detection-engine` to actually request `gradient_boosting_network_flow`, and giving it real
non-degenerate live features (a real flow collector, or a richer simulation payload), are real
follow-up work this run identified but did not implement — see
`docs/models/gradient_boosting_network_flow.md`'s "Live-detection readiness" section.
