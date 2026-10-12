# Phase 1.5 benchmark run `20261012T0715-phase1.5`

Commit `c160470b2a17` (CICIDS2017 reruns) / `34853ed0610f` (UNSW-NB15 audit, same branch, one commit earlier).
Full machine-readable detail: `unsw_nb15_official_audit.json`, `partial_cicids2017_v2.json` in this directory.

This run answers the user's Phase 1.5 leakage-audit and autoencoder-bug-hunt requests directly. It
**supersedes** the Phase 1 run (`20261012T054851Z-manual`) for UNSW-NB15's primary result and for
every autoencoder number on both datasets — see `docs/ML_BENCHMARK_REPORT.md`'s Phase 1.5 section
for the full real tables and before/after comparisons.

## Headline, real, measured

- **UNSW-NB15's earlier 2-of-4-row-file random split was leaking.** The official train/test
  partition (the authors' own split) gives materially lower, more honest numbers: LightGBM
  ROC-AUC 0.986 (official) vs. 0.9999 (random split); Isolation Forest 0.733 vs. 0.972.
  1,295 of test's 175,341 rows (1.28%) are exact-duplicate feature vectors of a train row.
- **The autoencoder bug is fixed.** Root cause: raw unscaled features, not score direction. After
  adding log1p + standardisation (fit on benign train only): CICIDS2017 day-split ROC-AUC
  0.617 → 0.822; CICIDS2017 known-attack split 0.868; UNSW-NB15 official split 0.753 (was 0.434,
  below chance).
- **`sttl` dominates UNSW-NB15's LightGBM decisions** (gain 367,838 vs. the next feature's
  151,561; mean |SHAP| 9.08 vs. 0.51) — a widely-cited criticism of this dataset in the literature.
  Removing it plus `dttl`/`ct_state_ttl` costs only 0.002 ROC-AUC (0.986 → 0.984), so the model
  isn't solely dependent on it despite the lopsided importance.
- **CICIDS2017's "known-attack" split is far easier than the day-based "unseen-attack" split**
  (LightGBM ROC-AUC 0.999983 vs. 0.753) — real evidence that day-boundary generalisation, not
  within-distribution classification, is where every model's real weakness is on this dataset.
