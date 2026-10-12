# Phase 1 dataset provenance

`data/raw/` is git-ignored (see `scripts/download_datasets.md` for placement/sourcing
instructions). This file records exactly what is actually in it on this machine right
now: real file identities (sha256, size, row count — all computed by
`scripts/verify_datasets.py`, copied verbatim from `data/metadata/*.json`), the real
mirror each came from, and its licence, so a reader never has to guess whether a number
downstream came from the official release or a third-party mirror.

**Both datasets below were sourced from Kaggle mirrors, not the official hosts.**
Flagged here, in `scripts/download_datasets.md`, and should be flagged again in
`docs/ML_BENCHMARK_REPORT.md` once a real run uses this data.

## CICIDS2017

- **Mirror used**: [`shadman1028/cicids2017-official-flow-feature-csv-files`](https://www.kaggle.com/datasets/shadman1028/cicids2017-official-flow-feature-csv-files) on Kaggle.
- **Licence**: Attribution 4.0 International (CC BY 4.0), as declared by the mirror.
- **Not the corrected release**: `scripts/download_datasets.md` recommends the Engelen/Rimmer/Joosen WTMC-2021 corrected release (fixes >20% mislabelled flows and known feature-extraction bugs in the original). No Kaggle mirror of that corrected release was found (searched 2026-10-12). This mirror ships the **original, uncorrected 2017 labels** — the mirror's own description states no preprocessing/relabelling/modification was applied, i.e. it is a faithful copy of the original CIC/UNB `MachineLearningCSV` release, not the corrected one.
- **Original source credited by the mirror**: Canadian Institute for Cybersecurity (CIC), University of New Brunswick (UNB) — <https://www.unb.ca/cic/datasets/ids-2017.html>.
- **Citation**: Sharafaldin, Lashkari, Ghorbani, *"Toward Generating a New Intrusion Detection Dataset and Intrusion Traffic Characterization,"* ICISSP 2018.

| file | sha256 | size | rows |
|---|---|---|---|
| Monday-WorkingHours.pcap_ISCX.csv | `852c4beb34eda186f32561fa79df7a0747e92e1a6535b01270820dd9ffe17f34` | 176,927,918 B | 529,919 |
| Tuesday-WorkingHours.pcap_ISCX.csv | `52b8692ae8c7d2ed04671fe2b98335693c0a92c7ab157d8c8b534d6523080851` | 135,078,995 B | 445,910 |
| Wednesday-workingHours.pcap_ISCX.csv | `893c27dc968bf7a8adef1689f90be55ca4a4dc3088fb63d6ff247ac56856df2a` | 225,166,395 B | 692,704 |
| Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv | `d67066211fb1689c78406f1506f4c44704ecb92088353d5c96d96d6474eb819d` | 52,023,263 B | 170,367 |
| Thursday-WorkingHours-Afternoon-Infilteration.pcap_ISCX.csv | `6bcda3857c2504676034e3ea57762d38393cc734cb377a726bd5cb153961b1b5` | 83,102,436 B | 288,603 |
| Friday-WorkingHours-Morning.pcap_ISCX.csv | `53a41c24d570ea83b7ac55b2e94df94e7a8216aeb80a2af0246b6bc8bb543000` | 58,316,725 B | 191,034 |
| Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv | `ca1824c51bfbb7b3c72290a11be04366ba8815878c6a1cc5c44cb1cee269e99b` | 76,906,168 B | 286,468 |
| Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv | `6ff1580f5f81c0ae28a26f7631721018577f5f7c5e0feac28b795fcfe7b411ee` | 77,123,859 B | 225,746 |

## CICIDS2017, corrected release (WTMC-2021) — downloaded 2026-10-12

Approved by the user and downloaded this session, superseding the "no Kaggle mirror found"
blocker noted above — **this is a direct download from the official project page, not a
mirror.**

- **Source**: Gints Engelen, Vera Rimmer, Wouter Joosen, *"Troubleshooting an Intrusion
  Detection Dataset: the CICIDS2017 Case Study,"* IEEE Security and Privacy Workshops (SPW)
  2021. Project page: <https://intrusion-detection.distrinet-research.be/WTMC2021/>.
- **Direct URL**: `https://intrusion-detection.distrinet-research.be/WTMC2021/Dataset/dataset.zip`
  (no registration). Real downloaded zip: 333,841,436 bytes, sha256
  `4d535da19795d85376ae1397d161329e3b06fc47d9a5a68cd9be2cd7ecee0f2a`.
- **Licence**: as published by the Distrinet research group (KU Leuven); research/academic
  use — see the project page for exact terms. Citation required if used in anything published.
  No SPDX identifier is declared by the publisher.
- **Real structure, different from the Kaggle mirror above**: 5 files, one per capture day
  (no morning/afternoon split) — `Monday-WorkingHours.csv` … `Friday-WorkingHours.csv`, ~2.1M
  rows total. Real column set still includes `Flow ID`/`Src IP`/`Dst IP`/`Timestamp` (dropped
  as leaky by `sm_ml.datasets.parquet_convert`, same as the other release). A real, documented
  correction visible directly in the data: distinguishes `"Bot"` from `"Bot - Attempted"` as
  separate labels (the original release conflated them) — a genuine fix this release makes,
  confirmed by reading the real label values, not just the paper's abstract.

| file | sha256 | size | rows |
|---|---|---|---|
| Monday-WorkingHours.csv | `580bc5b3a48ccaa9b61d6936bb88adb00a6a069a02c974e946bd324bc09971bc` | 208,244,807 B | 371,750 |
| Tuesday-WorkingHours.csv | `59d60eff01526b511fa575a08a9a0e241674276adf1aa07471c947f7d733e19a` | 178,453,210 B | 322,004 |
| Wednesday-WorkingHours.csv | `820446eb19713031827a1893871e30fb9da4c3b21ad5cd15d9a2ef6686a37583` | 291,529,516 B | 496,780 |
| Thursday-WorkingHours.csv | `3db32a8e9a4da80aa15fd0bbf69733c8de8c6e6147fe279770eec1be6c263d65` | 187,707,525 B | 362,369 |
| Friday-WorkingHours.csv | `8bf5a79222d2a553b75fe1ee81cc3ddff89b87befaef52e62368fdb2e3a79def` | 282,607,319 B | 547,916 |

## UNSW-NB15

- **Mirror used**: [`mrwellsdavid/unsw-nb15`](https://www.kaggle.com/datasets/mrwellsdavid/unsw-nb15) on Kaggle — already the documented fallback in `scripts/download_datasets.md`.
- **Licence**: Kaggle lists it as "unknown" with no explicit SPDX tag. The dataset's own description quotes the original authors directly: *"Free use of the UNSW-NB15 dataset for academic research purposes is hereby granted in perpetuity. Use for commercial purposes should be agreed by the authors."*
- **Filename fix**: the mirror ships the features file as `NUSW-NB15_features.csv` (a typo present in the original UNB release itself, carried through by the mirror). Renamed to `UNSW-NB15_features.csv` on download to match `scripts/verify_datasets.py`'s expected name — no content change, verified by re-running the script after the rename.
- **Original source credited by the mirror**: Australian Centre for Cyber Security (ACCS), UNSW Canberra — <https://research.unsw.edu.au/projects/unsw-nb15-dataset>.
- **Citation**: Moustafa, Nour, and Jill Slay, *"UNSW-NB15: a comprehensive data set for network intrusion detection systems (UNSW-NB15 network data set),"* MilCIS 2015.

| file | sha256 | size | rows |
|---|---|---|---|
| UNSW-NB15_1.csv | `7d851bbeabd27894ce39c8e78835c73341fc946652fb7743b9eff193b55eb511` | 168,979,718 B | 700,001 |
| UNSW-NB15_2.csv | `6130ad02873cc6069ae695cf2844f2e8c2e9a9a1b7532dd82ab8f202757cacf8` | 165,221,021 B | 700,001 |
| UNSW-NB15_3.csv | `ae990a96c3dfcd425ce2801aadb1727a34d5e0ae6d8215dbcdae60dedfaef640` | 154,588,103 B | 700,001 |
| UNSW-NB15_4.csv | `cdf563692d51d405541dd659ddcdad9fa01f001f05fe9fc4b67f00ca12fbc96a` | 97,588,754 B | 440,044 |
| UNSW-NB15_features.csv (renamed from `NUSW-NB15_features.csv`) | `c55f19cceebb6360dc50f44f8a5f246ccefbcf8a6c604ac1ad46e643869cafce` | 4,044 B | 50 |
| UNSW_NB15_training-set.csv (authors' own split, sanity-check only) | `734fe6642edf758f7c94d7d9149426b49d202fe8e7bf0bef47392489c3c0a559` | 15,380,800 B | 82,333 |
| UNSW_NB15_testing-set.csv (authors' own split, sanity-check only) | `bec7dd5ec88dc2a0ccc7a07879d338395ed7421750f675fd0339e07dfe0648fa` | 32,293,018 B | 175,342 |

Full machine-checked detail (including `checked_at` timestamps) lives in
`data/metadata/cicids2017.json` and `data/metadata/unsw_nb15.json`, written by
`scripts/verify_datasets.py` — this file is a human-readable summary of those, not a
separate source of truth. If the files on disk ever change, re-run the script; it will
fail loudly if a checksum no longer matches what's recorded here.
