# UNSW-NB15 — acquisition status

**Status: BLOCKED — NOT VERIFIED — REQUIRES MANUAL ACCESS AT THE SOURCE.**

- Name: UNSW-NB15 (Australian Centre for Cyber Security, UNSW Canberra)
- Checked live: 2026-10-06
- Primary host tried: `https://research.unsw.edu.au/projects/unsw-nb15-dataset`
  - Result: `200 OK`, but the page carries no working direct `.csv`/`.zip` link in its HTML. A `grep` of the fetched page for `cloudstor`/`researchdata`/`.zip`/`.csv` links found none.
- The dataset's historical host (AARNet CloudStor) is no longer available; the official project page has not been re-pointed at a working anonymous download in a scriptable form.
- License: as published by UNSW, subject to their terms (not re-checked here since the files were never reached).

## Manual steps to unblock (for the repository owner)

1. Visit `https://research.unsw.edu.au/projects/unsw-nb15-dataset` directly in a browser (the page may render download links via JavaScript that a plain HTTP fetch does not execute) and follow whatever current access path UNSW provides.
2. If UNSW requires an access request/agreement, complete it.
3. Download the CSV files (`UNSW-NB15_1.csv`..`UNSW-NB15_4.csv` plus the feature/label CSVs, per the dataset's own published layout).
4. Record the sha256 of each downloaded file.
5. Stage under `data/raw/unsw_nb15/` (outside git).
6. A dataset adapter analogous to `services/ml-training/src/sm_ml_training/benchmark/nsl_kdd.py` would need to be written against UNSW-NB15's actual 49-feature schema before it can be benchmarked — not yet written, since there was nothing to write it against.

No number is claimed for this dataset anywhere in this repository.
