# Phase 1.6 benchmark run `20261012T1433-phase1.6-final`

Commit `ee95b5a11f7e` (LightGBM production integration, UNSW-NB15 orientation fix) plus this
session's corrected-CICIDS2017 (WTMC-2021) rerun, consolidated into this one run-id.
Full machine-readable detail in this directory: `unsw_nb15_official_audit.json`,
`inference_latency_benchmark.json`, `partial_cicids2017_corrected.json`. Full real tables,
methodology, and honest discussion: `docs/ML_BENCHMARK_REPORT.md`'s "Phase 1.6" section.

This run answers the user's Phase 1.6 requests directly: split orientation, duplicate
sensitivity, base rates, the corrected-CICIDS2017 comparison, and production LightGBM
integration with a real latency/throughput benchmark.

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
- **Corrected CICIDS2017 (WTMC-2021) downloaded and run for real**, compared against the
  Kaggle mirror's original-label numbers already in this report. LightGBM's day-split
  (unseen-attack) ROC-AUC improves substantially on the corrected labels: 0.753472 → 0.953734 —
  consistent with the corrected release's own claim of fixing >20% mislabelled flows.
- **LightGBM is now actually served by `ml-inference`**, behind `SM_ML_ENABLE_GRADIENT_BOOSTING`
  (off by default) — confirmed it was NOT served before this session, not assumed. Real measured
  CPU latency: single-request p50 0.147 ms / p99 0.452 ms (6,090.5 flows/s); vectorised batch of
  1,000, p50 2.43 ms / p99 3.37 ms (411,234.9 flows/s).
- **The known-attack-vs-unseen-attack generalisation gap holds on every dataset tested.**
  LightGBM is near-perfect recognising attack types it saw in training (ROC-AUC up to 0.999983)
  but drops to 0.75–0.95 the moment the split holds out an attack type or capture day it never
  trained on — the real, central weakness this phase's evaluation keeps surfacing.

## Not yet done

Phase 2 (DARPA TC) was explicitly out of scope for this phase, per the user's instruction.
