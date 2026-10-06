# CICIDS2017 — acquisition status

**Status: BLOCKED — NOT VERIFIED — REQUIRES MANUAL REGISTRATION AT THE SOURCE.**

- Name: CICIDS2017 (Canadian Institute for Cybersecurity, UNB)
- Checked live: 2026-10-06
- Primary host tried: `http://205.174.165.80/CICDataset/CIC-IDS-2017/Dataset/{MachineLearningCSV,GeneratedLabelledFlows}.zip`
  - Result: `301 Moved Permanently` → `https://cicresearch.ca/CICDataset/...` → `302 Found` → `https://www.unb.ca/cic/datasets/index.html` (a 108,784-byte HTML landing/registration page, not a dataset file; `Content-Type: text/html`).
- No anonymous direct-download path exists any more for this dataset.
- License: as published by UNB CIC, subject to their terms (not re-checked here since the files were never reached).

## Manual steps to unblock (for the repository owner)

1. Visit `https://www.unb.ca/cic/datasets/ids-2017.html`, follow the dataset's own access/request process.
2. Download `MachineLearningCSV.zip` (the labelled flow CSVs most directly comparable to NSL-KDD's row format) and/or `GeneratedLabelledFlows.zip`.
3. Record the sha256 of each downloaded file.
4. Stage under `data/raw/cicids2017/` (outside git, per this repo's existing `SM_DATASET_ROOT` convention — see `README.md`).
5. A dataset adapter analogous to `services/ml-training/src/sm_ml_training/benchmark/nsl_kdd.py` would need to be written against CICIDS2017's actual column schema (different from NSL-KDD's 41 columns) before it can be benchmarked — not yet written, since there was nothing to write it against.

No number is claimed for this dataset anywhere in this repository.
