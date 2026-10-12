# Downloading the Phase 1 datasets

Both datasets go under `data/raw/<name>/` (git-ignored). After placing files, run:

```
python scripts/verify_datasets.py
```

It checks every expected file exists, computes a real sha256 and row count for each, and writes `data/metadata/<name>.json`. It fails loudly — non-zero exit, a clear message naming exactly what's missing — if anything is absent or a checksum later changes under you.

## CICIDS2017 — corrected release (recommended), no registration needed

**Use this instead of the original UNB files.** The original CICIDS2017 host now requires registration at UNB (confirmed live — the direct-download links redirect to `https://www.unb.ca/cic/datasets/ids-2017.html`, a request form). The corrected release below fixes real, published errors in the original and needs no registration.

- **Source**: Gints Engelen, Vera Rimmer, Wouter Joosen, *"Troubleshooting an Intrusion Detection Dataset: the CICIDS2017 Case Study,"* IEEE Security and Privacy Workshops (SPW) 2021. Official project page: <https://intrusion-detection.distrinet-research.be/WTMC2021/tools_datasets.html>
- **Direct download** (verified live, 2026-10-11, `Content-Length: 333841436` bytes ≈ 318 MB, zip of CSV files, no PCAPs): `https://intrusion-detection.distrinet-research.be/WTMC2021/Dataset/dataset.zip`
- **What it fixes**: over 20% of the original traffic flows were reconstructed/relabelled; packet misorder, packet duplication, mislabelled attacks, and feature-extraction bugs in the original CICFlowMeter tool are corrected.
- **Place at**: `data/raw/cicids2017/` — unzip there; one CSV per capture day is expected (Monday benign-only through Friday, per the original CICIDS2017 collection schedule this release preserves — needed for the day-based split, see Phase 1 plan).
- **Citation required** if this data or the fixed CICFlowMeter tool is used in anything published: cite the paper above.
- **Licence**: as published by the Distrinet research group (KU Leuven); research/academic use, see their page for exact terms.

### What was actually used on this machine

Both. The Phase 1/1.5 primary runs used the Kaggle mirror
[`shadman1028/cicids2017-official-flow-feature-csv-files`](https://www.kaggle.com/datasets/shadman1028/cicids2017-official-flow-feature-csv-files)
(CC BY 4.0, original uncorrected 2017 labels, unmodified CSVs, filenames matching
exactly what's listed above) — no Kaggle mirror of the corrected release exists
(searched 2026-10-12, none found). **Phase 1.6**: the real corrected release above was
then downloaded directly (approved by the user, no registration needed) and used for a
real LightGBM comparison against the mirror's uncorrected numbers — see
`docs/ML_BENCHMARK_REPORT.md`'s Phase 1.6 section. Full provenance, sha256s and the
licence note for both: see `data/README.md`.

### Known alternative, not used here: LYCOS-IDS2017

Rosay, Carlier et al. also corrected CICIDS2017 (feature duplication, wrong protocol detection, inconsistent TCP termination, labelling errors), producing *LYCOS-IDS2017*. Tooling: <https://github.com/17204612710214/lycos-ids2017> (mirror of <https://maupiti-git.univ-lemans.fr/lycos/lycos-ids2017>). **Not used**: their pipeline re-extracts features starting from the **original** UNB CICIDS2017 files, so it doesn't avoid the registration wall above — using it would mean registering at UNB anyway, with no access benefit over the Engelen release. Noted here in case a future comparison against it is wanted.

## UNSW-NB15 — official source, manual download (cloud-share link, not automated)

The official page's download link is a SharePoint folder — a cloud-share link, which per your instruction is not something to script.

- **Official page**: <https://research.unsw.edu.au/projects/unsw-nb15-dataset>
- **Direct SharePoint folder** (linked from that page, contains pcap/BRO/Argus/CSV files and reports): `https://unsw-my.sharepoint.com/:f:/g/personal/z5025758_ad_unsw_edu_au/EnuQZZn3XuNBjgfcUu4DIVMBLCHyoLHqOswirpOQifr1ag?e=gKWkLS`
- **Files needed** (CSV only — do not download the PCAP/BRO/Argus raw captures, outside the 15 GB Phase 1 disk budget and not needed for a flow-feature model):
  - `UNSW-NB15_1.csv`, `UNSW-NB15_2.csv`, `UNSW-NB15_3.csv`, `UNSW-NB15_4.csv` (the full ~2.54M-row flow set, in 4 parts)
  - `UNSW-NB15_features.csv` (the 49-feature schema/description — needed to name columns; the row files ship without a header)
  - `UNSW_NB15_training-set.csv`, `UNSW_NB15_testing-set.csv` (the dataset authors' own pre-split partitions, with a header and an `attack_cat` column — useful as a sanity check against our own split, not necessarily the split used for Phase 1's held-out-attack-type evaluation)
- **Place at**: `data/raw/unsw_nb15/`
- **Citation**: Moustafa, Nour, and Jill Slay. *"UNSW-NB15: a comprehensive data set for network intrusion detection systems (UNSW-NB15 network data set)."* Military Communications and Information Systems Conference (MilCIS), 2015.

### Fallback mirror, only if the SharePoint link doesn't work for you

Kaggle: <https://www.kaggle.com/datasets/mrwellsdavid/unsw-nb15> — a widely-used mirror of the same 4 CSV parts + feature list. **This is a mirror, not the official source** — if used, record its own file sizes/sha256 in `data/metadata/unsw_nb15.json` (the verify script does this automatically) and this file gets a note added recording that the mirror was used instead of the official SharePoint link.

### What was actually used on this machine

The SharePoint link was not used — this mirror was used instead. Its features file
ships as `NUSW-NB15_features.csv` (a typo in the original UNB release, carried
through by the mirror); renamed to `UNSW-NB15_features.csv` on download to match the
expected filename above, re-verified after the rename. Full provenance, sha256s and
the licence note (the mirror's own quote of the original authors' usage grant): see
`data/README.md`.
