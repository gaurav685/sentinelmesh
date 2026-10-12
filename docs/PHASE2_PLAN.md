# Phase 2 plan — provenance-graph GNN on DARPA TC CADETS E3

Branch `feat/provenance-gnn`, off `main`@`b8a9f33` (PR #1/#2 merged). Time-box: 2 weeks.
Same non-fabrication discipline as Phase 1: every number in this plan is either cited to a
real, fetched source, or explicitly marked as an estimate/unconfirmed — nothing here is a
guess presented as a fact. Approved limits: ~30 GB disk (raw+processed), CPU-only, peak RAM
under ~10 GB (mini-batch/time-window, never full-batch on the whole graph), Parquet/DuckDB
over Postgres unless label alignment proves that wrong.

## Auto-approval gate — checked against the 5 stated conditions

| # | Condition | Status | Basis |
|---|---|---|---|
| 1 | Ground-truth labels from a published, citable source | **MET — real label files secured, no hand-derivation needed** | Confirmed by cloning `ubc-provenance/PIDSMaker` directly: it already redistributes two independent third-party derivations of DARPA's own `tc_ground_truth_report_e3_update.pdf` for CADETS_E3 — ThreaTrace's flat 12,858-node-UUID list and Orthrus's 4 per-attack CSVs with real timestamps (76 attack-chain nodes total). Both copied into `data/ground_truth/cadets_e3/` with sha256s, cited in `data/README.md`. No hand-derivation from the PDF was needed. |
| 2 | Total disk fits in ~30 GB | **MET — now primary-confirmed** | **1.4 GB compressed / 10 GB loaded**, per `ubc-provenance/PIDSMaker`'s own install docs (<https://ubc-provenance.github.io/PIDSMaker/ten-minute-install/>, fetched directly) — resolves the earlier "unconfirmed" secondary figure from initial research. Comfortable margin under 30 GB. |
| 3 | Estimated training time per run under ~4 hours on this CPU | **NOT MET — no real estimate exists** | Checked both reference papers directly: KAIROS's paper (§5, Table 10) reports only per-time-window *inference* cost (median 2.5s, max 19.7s per 15-min window on a 20-core Xeon, no GPU) — total training wall-clock is never stated. ThreaTrace's paper (§VI-E) reports its own 16-vCPU/64GB CPU-only hardware but likewise never states total training time. Neither repo's README states one either (KAIROS's README says only "due to the extended amount of time it takes to train a model, we provide pre-trained models"). There is no real number to compare against the 4-hour bound — inventing one to pass this gate would be exactly the kind of fabrication this project's rule forbids. **This condition fails by default until a real pilot run produces a measured number.** |
| 4 | A baseline exists (published result and/or a simple non-GNN detector) | **MET** | Published: KAIROS Table 4 (time-window-level, CADETS_E3) and ThreaTrace Table VII (node-level, CADETS_E3) — both real, cited below. Non-GNN: this plan's own step 5(b) builds a LightGBM/rare-event-frequency baseline on the same node features, same convention as Phase 1's gradient-boosting comparison. |
| 5 | Reference repo's licence allows reuse | **MET** | `ubc-provenance/PIDSMaker`, **Apache-2.0** (confirmed via GitHub). The original `ubc-provenance/kairos` repo has **no licence file** (`license: null`) — used as an architecture/paper reference only, its code is not reused directly. |

**4 of 5 conditions are met; condition 3 cannot be met with a real number before a pilot run
exists. Per your own fallback instruction, this stops here — plan shown below, no download yet,
waiting for explicit go-ahead.**

## Week 1 status (after go-ahead) — real download blocker found, needs a decision

Approved and attempted. Real findings:

- **Ground-truth labels (gate 1) are done** — see table above and `data/README.md`'s new
  "Phase 2: DARPA TC CADETS E3" section. No PDF hand-derivation needed.
- **Raw CDM audit-log download is blocked by a real, confirmed Google Drive quota**, not a bug
  in this project. Tested `gdown` (installed this session) against two of the file IDs in
  PIDSMaker's `download_cadets_e3.sh` (one small schema file, one main data file) — both
  returned Google's real "Too many users have viewed or downloaded this file recently... may
  take up to 24 hours" error, independent of file size, meaning the whole shared folder's public
  anonymous-link quota is currently exhausted (a very popular public dataset).
- **Two real paths found, not yet chosen between:**
  1. **Wait and retry** the same anonymous `gdown` method later (quota may clear in anywhere
     from an hour to 24 hours per Google's own message). No new credentials needed; keeps the
     plan's original intent of parsing raw CDM/Avro records ourselves into Parquet.
  2. **Authenticated Google Drive API download**, found in PIDSMaker's own
     `download_datasets.sh` and install docs: `curl -H "Authorization: Bearer <TOKEN>"
     https://www.googleapis.com/drive/v3/files/<ID>?alt=media`. This uses a per-user OAuth2
     access token (obtained via Google's own OAuth 2.0 Playground) rather than the anonymous
     public link — authenticated API quota is normally separate from the exhausted anonymous
     one, so this would likely work *now*, but getting the token is an interactive Google login
     step only you can do (same category as `gcloud auth login` — not something to automate or
     ask you to paste a token for). **This project's own version of this path would point the
     same Bearer-token request at the raw CDM file IDs** (not PIDSMaker's pre-built Postgres
     dump, which would reintroduce a Postgres dependency and skip the parsing step the plan
     calls for) — worth trying if you want to unblock immediately rather than wait.
- **Decision needed**: wait for quota to clear (I can retry on a schedule), or get a token via
  the OAuth Playground yourself and run the authenticated download (I'll give the exact command
  once you have one) — your call.

Everything else not blocked by the raw download continues in parallel (this doc, ground truth
integration, Parquet/DuckDB schema design, parser scaffolding, small synthetic-fixture tests).

## 1. Reference repo + licence

**Primary: `ubc-provenance/PIDSMaker`** (Apache-2.0; last push 2026-10-09, actively maintained;
140 stars at research time). Re-implements KAIROS's architecture with first-class `CADETS_E3`
support (`python pidsmaker/main.py kairos CADETS_E3 ...`). Chosen as the base to build from.

Secondary references, not reused as code:
- `ubc-provenance/kairos` — the original KAIROS implementation (IEEE S&P 2024 paper, not
  USENIX Security as earlier assumed — correcting that here). **No licence file.** Used only
  to understand the architecture PIDSMaker re-implements and to cite its published numbers.
- `threaTrace-detector/threaTrace` — MIT licence, has its own CADETS parser
  (`scripts/parse_darpatc.py`). **Not reused for model training logic**: an independent
  reproducibility study (ACM REP'25, read directly) found its released training script
  evaluates sub-models against the test set *during* training and discards poor ones — a real
  test-set leakage bug. Disabling the leak drops its reported CADETS F1 from ~0.94 to 0.54. Its
  parsing code may still be a useful cross-check for the audit-log schema; its model-selection
  code is explicitly excluded.

## 2. Ground-truth label source

DARPA's own `ground_truth/tc_ground_truth_report_e3_update.pdf` (narrative, not machine-
readable) is the ultimate source, but **real, already-derived label files exist and were used
directly — no hand-derivation needed**, per the Week 1 status above:
- `data/ground_truth/cadets_e3/threatrace_node_labels.txt` — 12,858 node UUIDs (ThreaTrace's
  derivation), full attack-neighbourhood labelling, one combined window over the test period.
- `data/ground_truth/cadets_e3/node_Nginx_Backdoor_{06,11,12,13}.csv` — 8/4/43/24 attack-chain
  node UUIDs (Orthrus's derivation) with real per-attack time windows (below), a far narrower
  labelling than ThreaTrace's (28% node-level overlap, per PIDSMaker's own cross-check).

Real per-attack time windows (Orthrus, `US/Eastern`), reused directly for the time-window-level
evaluation KAIROS's own methodology uses:

| File | Window | Used in PIDSMaker's own reported results? |
|---|---|---|
| `node_Nginx_Backdoor_06.csv` | 2018-04-06 11:20–12:09 | Yes |
| `node_Nginx_Backdoor_11.csv` | 2018-04-11 15:07–15:16 | No — excluded by their own config; kept here, inclusion decided once we see real detection behaviour on it |
| `node_Nginx_Backdoor_12.csv` | 2018-04-12 13:59–14:39 | Yes |
| `node_Nginx_Backdoor_13.csv` | 2018-04-13 09:03–09:16 | Yes |

Known attack in this engagement (KAIROS Table 11, confirmed from the paper): FreeBSD host,
55-minute window, Nginx exploited by `81.49.200.166`, payload dropped to `/tmp/vUgefal`,
executed as root, lateral-movement attempt to two IPs (one succeeds: `61.167.39.128`), a failed
`sshd` injection attempt via `/var/log/devc`. This is the concrete attack chain detection is
evaluated against.

**Licence/usage terms for the data itself**: stated directly in `README-E3.md` — released by
DARPA into the public domain for research, "as-is," with no warranty. No formal OSS licence
file; this is DARPA's own public-domain release statement, cited directly.

## 3. Download size

**1.4 GB compressed / 10 GB loaded**, per `ubc-provenance/PIDSMaker`'s own install docs
(fetched directly) — comfortably inside the ~30 GB budget alongside the Parquet/DuckDB
conversion and model checkpoints. Graph scale per KAIROS's own measurement: 178,965 nodes,
10.1M edges, 1,248 attack edges (0.012% of all edges). ThreaTrace's paper reports a different
split of the same corpus (706,966 benign + 12,852 abnormal nodes, 8.66M edges) — the two papers
used different subsets/windows of the same E3-CADETS data; whichever split this project adopts
will have its own real counts reported once the raw data is actually loaded (blocked — see
Week 1 status above), not borrowed from either paper.

## 4. Expected training time on this CPU

**No real number exists yet in any source — see gate condition 3 above.** What is confirmed:
both KAIROS (20-core Xeon, 64 GB RAM) and ThreaTrace (16 vCPU, 64 GB RAM) trained **CPU-only,
no GPU** — so CPU-only training is the originally-validated setup for this class of model, not
a downgrade expected to fail. Plan: Week 1 ends with a real pilot run (a small time-window
slice, mini-batch neighbour sampling) that produces an actual measured per-epoch and
total-training time on this machine. That measured number, not a guess, is what gets checked
against the 4-hour budget before Week 2's full run is committed to.

## 5. Evaluation methodology

Published numbers to compare against (both read directly from the primary PDFs):
- **KAIROS, time-window-level** (Table 4, independently reproduced exactly per ACM REP'25):
  precision 0.800, recall 1.000, AUC 0.997 (TP=4, TN=174, FP=1, FN=0 — a very small window count).
- **ThreaTrace, node-level** (Table VII, its own CADETS_E3 split): precision 0.90, recall 0.99,
  F1 0.94 (TP=12,848, FP=1,361, FN=4) — but see the test-leakage caveat above; treat this
  number as optimistic, not a clean target.
- **A real, open caution on KAIROS's own number**: an unresolved GitHub issue
  (`ubc-provenance/kairos#14`) found the original evaluation covered only 2 of the engagement's
  10 days and 1 of 3 real attacks; extending to the full window dropped precision to 26.32% and
  recall to 62.5%. This project's evaluation deliberately covers the **full available CADETS_E3
  time range**, not just the easiest 2-day window, specifically to avoid repeating that gap.

This project's own evaluation reports:
- Node-level precision/recall/F1 against the derived ground-truth labels.
- False positives per day across the full engagement window (the metric the published papers
  under-report by only evaluating a narrow window).
- Per-attack-scenario detection: pass/fail on each real step of the Nginx/lateral-movement/
  `sshd`-injection chain above, not just an aggregate score.
- Head-to-head comparison against both published numbers and this project's own non-GNN
  baseline (step 5b), with an explicit explanation if this project's numbers come out worse —
  no silent omission of an unfavourable result.

## Steps (as specified)

1. Download CADETS_E3 (or PIDSMaker's preprocessed release, whichever is real and verifiable),
   checksum it, record source/licence/sha256 in `data/README.md` — same convention as Phase 1.
2. Parse audit records to Parquet: `events` (subject, object, type, timestamp), `entities`
   (process/file/socket). DuckDB over the raw Parquet for querying; Postgres only if label
   alignment turns out to need relational joins DuckDB genuinely can't do at this scale (10.1M
   edges is well within DuckDB's comfortable range — expected not to be needed, but checked for
   real before ruling it out).
3. Build the typed, timestamped provenance graph. Time-based train/test split: train on benign
   periods, test on periods containing the real attack window(s).
4. Align derived ground-truth labels to nodes; report real label counts (not estimated).
5. Baselines: (a) reproduce KAIROS's/ThreaTrace's published result if the pipeline allows it
   directly, (b) a simple non-GNN detector (rare-event frequency, or LightGBM on node features
   — same model family as Phase 1's `gradient_boosting_network_flow`, different data).
   **Stop here — check-in 1: data stats + baseline results.**
6. GraphSAGE-style GNN (or PIDSMaker's own method), trained on benign activity only, mini-batch
   neighbour sampling or time-window subgraphs — never full-batch on the whole graph, keeping
   peak RAM under ~10 GB by construction, watchdog on (same memory-crisis lesson as Phase 1).
7. Evaluate per the methodology above; honest comparison against baselines and published
   numbers, with an explanation if this project underperforms either.
8. Offline integration only: export detections as evidence loadable into SentinelMesh's Neo4j
   attack-chain correlation, a small demo script — explicitly **offline-benchmark only**, same
   framing as the LightGBM model card from Phase 1 (no claim of live wiring into
   `detection-engine` without the same kind of live-feature-compatibility check that model got).
9. Tests (parsing, graph building, label alignment — small real fixtures, not full-scale data),
   CI green, a model card, results folded into `docs/ML_BENCHMARK_REPORT.md`.
   **Stop here — check-in 2: final results table, files changed, 2 resume bullets from measured
   numbers only.**

## Unconfirmed items, carried forward from research (not guessed, flagged)

- File-level public accessibility of the Five Directions Google Drive folder —
  **now confirmed blocked** (real quota error, not merely unconfirmed), see Week 1 status above.
- Total training wall-clock for either reference system (the reason gate condition 3 is unmet) —
  still unconfirmed; needs the pilot run, still blocked on raw data.
- Whether Unicorn/ProvDetector/Rapsheet/Flash/Orthrus have real, working CADETS_E3 scripts —
  Orthrus confirmed real (its ground-truth derivation is in active use, above); Unicorn/
  ProvDetector/Rapsheet/Flash still not found, not assumed to exist.
- Exact raw-vs-processed size split — **resolved**: 1.4 GB / 10 GB, primary-confirmed above.
