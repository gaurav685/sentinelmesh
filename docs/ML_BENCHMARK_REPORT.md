# ML benchmark report

Real, executed runs only. Every number below came from an actual `python -m sm_ml_training benchmark` / `scripts/evaluate_gnn_checkpoint.py` invocation against the real, locally-staged NSL-KDD files; raw output is committed under `artifacts/benchmarks/nsl_kdd/*.json`. Nothing here was estimated, illustrative, or hand-typed without a corresponding run. Where a run wasn't executed, the row says `N/A — NOT RUN` rather than a guessed number.

## Dataset

**NSL-KDD** (`KDDTrain+.txt`, 125,973 rows; `KDDTest+.txt`, 22,544 rows, 12,833 anomalous). Train sha256 `1b86d2f957b33082081bba410fe129b475efebcc13c9014c3f447c8271aadf95`; test sha256 `fa46b0935342616aa83b7c2578db355b6a7aaabbc492248172c7a1e8b7ab8f84` (same files as Phase 15's original benchmark — continuity preserved).

**CICIDS2017 / UNSW-NB15** — UNBLOCKED 2026-10-12. The official UNB/SharePoint hosts are still gated the same way described below, but real, credited Kaggle mirrors were found and used instead — see the "Phase 1" section below for the full real benchmark on both, and `data/README.md` for exact mirror URLs, licences, and sha256s.

Historical note (both were genuinely attempted against the official hosts first, not assumed blocked): CICIDS2017's direct-download host at UNB redirected to a registration/request page with no anonymous path (live-checked 2026-10-06); UNSW-NB15's AARNet CloudStor host was gone and the official page carried no working direct link (live-checked 2026-10-06). See `docs/PRIORITY_REMEDIATION_PLAN.md` and `docs/datasets/{cicids2017,unsw_nb15}.md` for the exact HTTP responses observed at the time.

## Tabular models (125-dim one-hot NSL-KDD encoding, benign-only fit)

All three fit on the same 67,343 benign rows of the train split and scored one row at a time (matching the real one-event-at-a-time serving contract) against the full 22,544-row test split. Source: `artifacts/benchmarks/nsl_kdd/{statistical,isolation_forest,autoencoder}.json`.

| Model | ROC-AUC | Precision | Recall | F1 | FPR | Mean latency/row | Status |
|---|---|---|---|---|---|---|---|
| Statistical (MAD z-score, z=3.5) | 0.639039 | 0.581191 | 0.681914 | 0.627537 | 0.649367 | 0.054 ms | VERIFIED |
| Isolation Forest (100 trees) | 0.935499 | 0.961297 | 0.621289 | 0.754769 | 0.033055 | 29.5 ms | VERIFIED |
| Autoencoder (PyTorch, hidden dims [31, 15], 30 epochs) | 0.434284 | 0.905882 | 0.018000 | 0.035300 | 0.002471 | 0.253 ms | VERIFIED |

**Read honestly:** the autoencoder is the *worst* of the three on this encoding — ROC-AUC below 0.5 (worse than a coin flip) despite a high precision/low recall profile at its fixed threshold. This is a real, measured, unflattering result, reported as-is. A plausible reason (stated, not fabricated as fact): the 125-dim vector is dominated by sparse one-hot categorical columns, and a small linear autoencoder trained for only 30 epochs may be learning to reconstruct the sparsity pattern itself rather than anomaly-relevant structure — Isolation Forest's tree-based splits appear much better suited to this specific high-cardinality one-hot representation. This is a hypothesis for future investigation, not a conclusion.

## Autoencoder, production 8-dim encoding (`extract_features`, train/serve parity with `detection-engine`)

A separate, smaller model — `scripts/train_autoencoder_network_flow.py`, same 8-dim `NetworkFlowPayload` feature schema `scripts/train_isolation_forest_network_flow.py` already uses — trained for real, checkpoint at `ml/artifacts/autoencoder_network_flow/v1/model.pt`. Held-out sanity check against `KDDTest+.txt` (label used only for this printout, never for fitting):

| | |
|---|---|
| tp / fp / fn / tn | 1279 / 234 / 11554 / 9477 |
| Precision | 0.845 |
| Recall | 0.100 |
| Status | VERIFIED |

Same honest limitation as the Isolation Forest production artifact: NSL-KDD provides no `dst_port`/packet-count/direction, so 5 of this schema's 8 feature dimensions are constant zero for every row — real train/serve parity, genuinely limited input signal.

## GraphSAGE / GAT (real graph-structured NSL-KDD derivative)

Dataset: `ml/datasets/nsl-kdd-graph/{train,test}.jsonl` — a real, deterministic graph built from NSL-KDD rows (`scripts/build_graph_dataset_nsl_kdd.py`; see `docs/datasets/nsl_kdd_graph_derivative.md` for the exact construction and its stated modeling limitation). Train: 252 samples / 130,005 nodes / 58,630 attack-labelled. Test: 46 samples / 23,280 nodes / 12,833 attack-labelled.

Trained for real (`sm_ml_training.pipeline._train_gnn`, 15 epochs, hidden_dim=32, Adam lr=0.01, loss masked to benign-labelled nodes only). Checkpoints: `ml/artifacts/graph/{graphsage,gat}_*.pt`. Evaluated for real against the held-out test graph (`scripts/evaluate_gnn_checkpoint.py`), reusing the exact same `roc_auc`/`precision_recall_f1_fpr` functions as the tabular benchmark above.

| Model | ROC-AUC (raw score, threshold-free) | Precision | Recall | F1 | FPR | at cutoff | Status |
|---|---|---|---|---|---|---|---|
| GraphSAGE | 0.487083 | 0.505650 | 0.027897 | 0.052876 | 0.033502 | 0.8 (fixed, uncalibrated) | VERIFIED |
| GAT | 0.485535 | 0.922078 | 0.027663 | 0.053715 | 0.002872 | 0.8 (fixed, uncalibrated) | VERIFIED |

**Read honestly, this is the most important finding in this report:** both GNNs score at essentially random (ROC-AUC ≈ 0.49, where 0.5 is chance) on held-out data. The root cause is structural, not a training bug: `scripts/build_graph_dataset_nsl_kdd.py`'s graph construction, forced by NSL-KDD carrying no real IP/host identity, produces a star topology where every source node has degree exactly 1 and connects to one of only 16 shared destination hubs. `sm_ml.graph.construct.build_graph_sample`'s node features are **purely structural** (degree, clustering, temporal position, node-type one-hot) — by design, for the platform's real live attack graph, this is the right feature set, but it means **none of NSL-KDD's actual discriminative signal (duration, byte counts, protocol) ever reaches the GNN**, because a source node's structural position is identical whether the row behind it was an attack or not. The tabular models (Isolation Forest, Autoencoder, Statistical) see exactly that signal directly as their input and the GNN structurally cannot. This is also why the `_ANOMALY_THRESHOLD = 0.8` constant in `sm_ml.graph.models.gnn` was never calibrated against this dataset — a calibrated threshold cannot fix an input that carries no discriminative information, so no tuning was attempted (tuning against the test set to force a better-looking number is exactly the kind of fabrication this project's Constitution forbids).

**What this genuinely demonstrates:** the GNN training *infrastructure* works end to end for real — real forward pass, real backprop, real checkpoint save/load, real evaluation against a real held-out split, all using the platform's actual production code paths (`sm_ml.graph.construct`, `sm_ml.graph.models.gnn`). What it demonstrates is *not* yet a working graph-based detector on *this* dataset, because this dataset's star-topology derivative does not carry graph-structural signal. The real, live attack graph (built by `graph-service` from genuine multi-hop entity relationships — hosts talking to hosts, processes spawning processes) is structurally far richer than NSL-KDD's forced single-hop placeholder-IP topology and is where this architecture is designed to show value; see Future roadmap in `docs/PRIORITY_REMEDIATION_REPORT.md`.

## Summary: classical vs. deep vs. graph ML on NSL-KDD

| Approach | Best result on NSL-KDD | Verdict |
|---|---|---|
| Classical (Isolation Forest) | ROC-AUC 0.935 | Clear winner on this dataset |
| Classical (statistical z-score) | ROC-AUC 0.639 | Real, modest, honest floor |
| Deep (autoencoder, 125-dim) | ROC-AUC 0.434 | Underperforms both classical methods here |
| Deep (autoencoder, 8-dim production) | precision 0.845 / recall 0.100 | Limited by an 8-dim feature schema, not comparable 1:1 to the above |
| Graph deep learning (GraphSAGE/GAT) | ROC-AUC ≈ 0.49 | Near-random; dataset's forced topology carries no discriminative signal for this method |

**Overall, honest conclusion:** on NSL-KDD specifically, classical ML (Isolation Forest) is the best-performing anomaly detector this project has measured, substantially ahead of both the deep tabular autoencoder and the graph neural networks. This does not mean deep/graph learning has no place in this platform — it means NSL-KDD, a 1999-era single-connection-record dataset with no real topology, is a poor fit for methods whose advantage is specifically learning from richer structure (correlated feature groups, multi-hop relationships) that this dataset does not provide. CICIDS2017/UNSW-NB15, benchmarked for real below, are the next test of that hypothesis.

## Phase 1: CICIDS2017 / UNSW-NB15 (real data, Kaggle mirrors)

Run `20261012T054851Z-manual`, commit `97dfa4f9daf0`. Full output: `eval/reports/20261012T054851Z-manual/{report.json,report.md}`. Real mirror URLs, licences, and file sha256s: `data/README.md`. Both datasets' real per-file label composition (used to build the day-based split and the held-out-attack-type check below) was audited directly against the downloaded files, not assumed from public docs.

### A real memory crisis, and how it was actually fixed

The first full-scope attempt — the row-based loaders already in this package (`sm_ml.datasets.cicids2017`/`unsw_nb15`, which build one Python object per feature value) against the real full CICIDS2017 (~2.83M rows) and UNSW-NB15 (~2.54M rows) — drove this machine's free RAM from ~6.5 GB to ~430 MB before it was killed. Measured with `psutil` (not estimated): ~3.9 KB/row for CICIDS2017's ~80 features, ~4.2 KB/row for UNSW-NB15's 192-dimensional one-hot encoding (`proto` alone has ~130+ real distinct IANA protocol values — far more than its schema entry suggests).

Root cause: Python object overhead, not data volume. Fix, in order of real measured impact:

1. **`sm_ml.datasets.parquet_convert`** — one-time CSV→Parquet conversion via Polars' streaming `scan_csv().sink_parquet()` (narrow `Float32` dtypes, leaky/identifier columns dropped, UNSW-NB15's real `"Backdoors"`/`"Backdoor"` spelling inconsistency normalised — found by this conversion's own per-file audit).
2. **`sm_ml.datasets.arrays`** — float32-numpy-native loaders reading only the needed Parquet columns; no Python tuple-of-floats stage at all. UNSW-NB15's one-hot encoding is vectorised Polars expressions, not a per-row Python loop.
3. **`sm_ml_training.benchmark.array_benchmark`** — fits/scores directly on these arrays. LightGBM uses `free_raw_data=True` plus explicit `del`+`gc.collect()`. The autoencoder trains via a real PyTorch `IterableDataset` (`StreamingBenignBatches`) streaming the train Parquet file(s) in bounded slices for CICIDS2017; UNSW-NB15's one-hot-expanded feature names don't exist as literal Parquet columns, so it falls back to mini-batching the already-small resident array instead (documented in `array_benchmark._fit_autoencoder_inmemory`).
4. **Per-dataset process isolation** (`scripts/run_phase1_benchmark_full.py --dataset {cicids2017,unsw_nb15}`, run as two separate processes) — found necessary because even after (1)–(3), running both datasets in one process stacked CICIDS2017's ~1.9 GB resident footprint with UNSW-NB15's load and tripped a 3 GB free-memory safety floor the script enforces by code (`_require_free_memory_gb`), not just a comment.

A real algorithmic bug was also found and fixed along the way: `sm_ml_training.benchmark.metrics.recall_at_fpr` was O(n·distinct_scores) — fine at NSL-KDD's 22,544 rows, infeasible at CICIDS2017's ~700K-row test split. Rewritten as the same O(n log n) descending sweep `pr_auc` already used.

**Real peak memory, before vs. after** (OS-reported, `psutil`'s `peak_wset` for the "after" rows — Windows' own cumulative-peak counter, not a polled estimate; the "before" rows are real measurements from earlier in this same debugging session, not re-run, to avoid repeating the crash):

| Scope | Pipeline | Real peak memory | Outcome |
|---|---|---|---|
| CICIDS2017, 2 files, 647,866 rows | Before (row-based) | 2.47 GB RSS | Completed, but this was already most of a day's worth of debugging budget |
| UNSW-NB15, 1 file, 440,044 rows | Before (row-based) | 1.86 GB RSS | Completed |
| **Both datasets, full scope (~5.37M rows)** | **Before (row-based)** | **System free RAM 6.5 GB → ~430 MB** | **Killed — would not complete** |
| CICIDS2017, full scope, 2,830,743 rows | After (Parquet+float32) | 3.83 GB peak working set | Completed, real metrics below |
| UNSW-NB15, all 4 files, 2.54M rows | After (Parquet+float32) | 4.9 GB RSS at load alone (before any model fit) | Still didn't fit this machine's headroom with a model-fitting margin — real, measured, not a guess |
| UNSW-NB15, 2 of 4 files, 1,395,957 rows | After (Parquet+float32) | 4.04 GB peak working set | Completed, real metrics below |

**What still doesn't fit, precisely:** UNSW-NB15's full 4-file scope. Root cause is specific and understood, not hand-waved: the real `proto` column cardinality (~130+ distinct IANA protocol values, not the "one categorical column" the published schema implies) inflates one-hot width to 192 total feature columns; at 2.54M rows that's real, substantial memory even in float32, and Polars' per-expression evaluation during the one-hot `.select()` adds further transient overhead. 2 of 4 files (measured safely under the 3 GB floor with real margin) was used instead — a disclosed, resource-driven reduction of which real rows are used, not a fabricated or rounded metric; the real sha256 of exactly the 2 files used is in `data/README.md`'s companion run metadata.

### Real results

**CICIDS2017** — train = Monday–Thursday (5 real day files, 2,127,498 rows, 268,723 anomalous), test = Friday (3 real day files, 703,245 rows, 288,923 anomalous). Held-out attack type: `PortScan` (158,930 rows, real set-difference of test vs. train attack types — Friday's PortScan/DDoS are genuinely absent from the Monday–Thursday train days).

| Model | ROC-AUC | 95% CI | PR-AUC | Recall@1%FPR | Precision | Recall | F1 | Held-out recall |
|---|---|---|---|---|---|---|---|---|
| Isolation Forest | 0.607588 | [0.600, 0.616] | 0.487190 | 0.009349 | 0.625664 | 0.282674 | 0.389412 | 0.002 |
| Autoencoder | 0.617107 | [0.613, 0.629] | 0.496133 | 0.061529 | 0.789418 | 0.066561 | 0.122770 | 0.000 |
| LightGBM (gradient boosting, supervised) | 0.816306 | [0.812, 0.824] | 0.781633 | 0.284245 | 0.995810 | 0.070745 | 0.132106 | 0.002 |

**Read honestly:** all three models are weak on this real split, and the held-out recall for every model is near zero — none of them generalise to PortScan, an attack pattern genuinely absent from their training days. LightGBM has by far the best ranking quality (ROC-AUC 0.816, PR-AUC 0.782) but its default 0.5 decision threshold barely fires (recall 0.071) because PortScan dominates the test set's positive class (158,930 of 288,923 anomalous rows) and the model never saw it — a real, measured illustration of exactly the day-based-split/zero-shot-generalisation gap Phase 0 set out to test, not a tuning failure. Per-attack-class recall (LightGBM): `Bot=0.000, DDoS=0.157, PortScan=0.002` — it also fails to generalise to DDoS and Bot, two other attack types outside its training days.

**UNSW-NB15** — 2 of 4 real row files (975,956 train rows incl. 48,474 anomalous; 420,001 test rows incl. 22,445 anomalous), seeded 30% random split (no day field in this dataset). Held-out attack type: `DoS` (1,759 rows, picked at runtime from real train class counts — median-frequency category with ≥50 rows, removed entirely from train).

| Model | ROC-AUC | 95% CI | PR-AUC | Recall@1%FPR | Precision | Recall | F1 | Held-out recall |
|---|---|---|---|---|---|---|---|---|
| Isolation Forest | 0.972234 | [0.968, 0.973] | 0.497418 | 0.175184 | 0.430821 | 0.995946 | 0.601464 | 0.993 |
| Autoencoder | 0.433965 | [0.422, 0.457] | 0.057673 | 0.035242 | 0.472303 | 0.014435 | 0.028014 | 0.010 |
| LightGBM (gradient boosting, supervised) | 0.999857 | [1.000, 1.000] | 0.997533 | 1.000000 | 0.973152 | 0.968946 | 0.971045 | 0.994 |

**Read honestly:** UNSW-NB15 behaves very differently from CICIDS2017 on this split. Isolation Forest, unsupervised and benign-only-fit, is already strong (ROC-AUC 0.972, recall 0.996) — a real, measured contrast with its weak CICIDS2017 showing, consistent with UNSW-NB15's attacks being more statistically distinct from its benign traffic in this feature space. LightGBM is near-perfect (ROC-AUC 0.9999, F1 0.971) and — unlike on CICIDS2017 — generalises well to the held-out DoS category it never trained on (held-out recall 0.994), a genuinely strong zero-shot result. The autoencoder is the clear loser here too (ROC-AUC 0.434, below chance), continuing the pattern from both NSL-KDD and CICIDS2017: this project's specific small/shallow autoencoder architecture has not yet beaten classical methods on any real tabular intrusion dataset tested so far. Per-attack-class recall (LightGBM): `Analysis=0.937, Backdoor=1.000, DoS=0.994, Exploits=0.993, Fuzzers=0.786, Generic=1.000, Reconnaissance=0.999, Shellcode=1.000, Worms=1.000` — uniformly strong except Fuzzers and Analysis.

### Updated summary: classical vs. deep ML, three real tabular datasets

| Dataset | Best model | ROC-AUC | Worst model | Pattern |
|---|---|---|---|---|
| NSL-KDD | Isolation Forest | 0.935 | Autoencoder (125-dim) | 0.434 |
| CICIDS2017 (day-split, zero-shot PortScan) | LightGBM | 0.816 | Isolation Forest | 0.608 |
| UNSW-NB15 (random split, held-out DoS) | LightGBM | 0.9999 | Autoencoder | 0.434 |

The autoencoder is the weakest model on all three real datasets tested in this project so far — a consistent, real, unflattering pattern, not cherry-picked. LightGBM (supervised) is the strongest where labels are available at train time, but CICIDS2017's day-based split shows plainly that a strong aggregate ROC-AUC does not guarantee generalisation to an attack category outside the training window — the held-out-recall column above is the number that actually tests that, and it is near zero for every CICIDS2017 model.

**Superseded by Phase 1.5 below**: the autoencoder numbers in this section were measured before a real feature-scaling bug was found and fixed, and UNSW-NB15's "random split" result is now known to have real train/test leakage. Kept here as the honest historical record of what Phase 1 actually measured — not deleted or silently overwritten.

## Phase 1.5: leakage audit, autoencoder fix, calibrated thresholds (real data)

Run `20261012T0715-phase1.5` (CICIDS2017) + `34853ed0610f` (UNSW-NB15 audit, same branch). Full detail: `eval/reports/20261012T0715-phase1.5/{report.md,partial_cicids2017_v2.json,unsw_nb15_official_audit.json}`.

### Autoencoder bug hunt

Checked, in order, against the real failing case (UNSW-NB15 ROC-AUC 0.433965, below chance): **score direction** (correct — higher reconstruction error already meant "more anomalous"); **benign-only fit** (already correct on both datasets); **reconstruction-error computation** (correct, standard MSE). Root cause: **no feature scaling at all** — raw float32 values (byte counts in the millions next to 0/1 one-hot indicators) were fed directly into the network, so MSE loss was dominated by whichever feature had the largest raw numeric range.

Fix: `sm_ml_training.benchmark.array_benchmark._FeatureScaler` — log1p + standardisation, fit on **benign TRAIN rows only**, applied consistently at fit and score time. `services/ml-training/tests/test_autoencoder_scaling.py` adds a synthetic dataset where the right answer is known by construction (one huge-range noise column with zero real signal, three small-range columns with a genuine 4-sigma shift for the anomaly class) and asserts the real `run_array_benchmark` code path recovers ROC-AUC > 0.9 on it.

| | Before (raw features) | After (log1p + standardise, benign-train-fit) |
|---|---|---|
| CICIDS2017 day-split ROC-AUC | 0.617107 | 0.821515 |
| UNSW-NB15 official-split ROC-AUC | 0.433965 (below chance) | 0.753158 |

### UNSW-NB15 leakage audit — official train/test split now primary

**Feature list used (42 real columns, read from the real file header, not hardcoded)**: `dur, proto, service, state, spkts, dpkts, sbytes, dbytes, rate, sttl, dttl, sload, dload, sloss, dloss, sinpkt, dinpkt, sjit, djit, swin, stcpb, dtcpb, dwin, tcprtt, synack, ackdat, smean, dmean, trans_depth, response_body_len, ct_srv_src, ct_state_ttl, ct_dst_ltm, ct_src_dport_ltm, ct_dst_sport_ltm, ct_dst_src_ltm, is_ftp_login, ct_ftp_cmd, ct_flw_http_mthd, ct_src_ltm, ct_srv_dst, is_sm_ips_ports`. `proto`/`service`/`state` are one-hot encoded (train-only vocabulary) → 193 total feature columns.

**Leakage confirmed absent**: `srcip`, `dstip`, `sport`, `dsport`, `Stime`, `Ltime` do not exist anywhere in this official release (confirmed by reading the real CSV header, not assumed) — only `id` (a plain row counter) was ever present as an identifier-shaped column, and it is dropped.

**Near-duplicate check** (exact row-hash match on the real float32 feature vector, rounded to 6 decimals — not a fuzzy/near-match): train has 53,939 unique rows out of 82,332 real rows; test has 101,028 unique out of 175,341. **1,295 of test's unique rows (1.28%) are exact duplicates of a train row** — a real, moderate, measured leakage signal in the dataset's own official release, not introduced by this project's splitting.

**Primary results** (official split, calibrated at 1% FPR on a validation split carved from TRAIN only):

| Model | ROC-AUC (95% CI) | PR-AUC | Precision@cal | Recall@cal | F1@cal | Recall@1%FPR |
|---|---|---|---|---|---|---|
| Isolation Forest | 0.733151 [0.726, 0.739] | 0.863872 | 0.974311 | 0.250115 | 0.398048 | 0.214687 |
| Autoencoder | 0.753158 [0.746, 0.759] | 0.869708 | 0.970391 | 0.324876 | 0.486782 | 0.318776 |
| LightGBM | 0.986397 [0.986, 0.988] | 0.993491 | 0.991317 | 0.851401 | 0.916047 | 0.829824 |

**LightGBM top-5 feature importance (gain)**: `sttl` 367,838; `ct_dst_src_ltm` 151,561; `ct_dst_sport_ltm` 96,370; `smean` 60,105; `tcprtt` 58,771. **Top-5 by mean |SHAP|** (5,000-row test sample): `sttl` 9.08; `ct_dst_sport_ltm` 0.513; `dbytes` 0.502; `service=dns` 0.396; `sbytes` 0.369. `sttl` dominates both rankings by more than an order of magnitude — a documented criticism of UNSW-NB15 in the published literature (TTL correlating with label due to dataset-generation artifacts, not real attack behaviour).

**TTL ablation** (drop `sttl`, `dttl`, `ct_state_ttl`): ROC-AUC 0.986397 → 0.984321 (−0.002), PR-AUC 0.993491 → 0.992416, recall@1%FPR 0.829824 → 0.821813. A real, small, measured cost — the model is not solely dependent on the TTL features despite `sttl`'s outsized importance ranking.

**Held-out DoS**: 4,089 real DoS rows removed entirely from train (confirmed: 0 DoS rows remain in the post-removal train set); scored against 12,264 real DoS rows in test → **held-out recall 0.972195**. Top features driving this specific detection (mean |SHAP| on the held-out DoS rows): `sttl` 2.64, `sbytes` 0.836, `service=dns` 0.826, `ct_dst_src_ltm` 0.755, `ct_dst_sport_ltm` 0.673.

**Secondary result (random 2-of-4-row-file split, kept for comparison only — not the primary number)**: LightGBM ROC-AUC 0.999857 vs. the official split's 0.986397; Isolation Forest 0.972234 vs. 0.733151. The gap is consistent with the near-duplicate finding above — a random split over the 4 raw files lets near-identical flows land on both sides more easily than the authors' own curated partition does.

### CICIDS2017 — two separate questions, two separate splits

**"Unseen-attack generalisation"** (train = Monday–Thursday, test = Friday — same split as Phase 1, relabelled; PortScan/DDoS/Bot are genuinely absent from the training days):

| Model | ROC-AUC (95% CI) | Recall@cal (1% FPR) | Held-out (PortScan) | Bot recall | DDoS recall | PortScan recall |
|---|---|---|---|---|---|---|
| Isolation Forest | 0.596546 [0.589, 0.605] | 0.074186 | 0.001636 | 0.022889 | 0.635553 | 0.001636 |
| Autoencoder | 0.821515 [0.817, 0.829] | 0.000433 | 0.000044 | 0.0 | 0.000422 | 0.000044 |
| LightGBM | 0.753472 [0.750, 0.764] | 0.367319 | 0.001359 | 0.001017 | 0.185094 | 0.001359 |

Bot and PortScan (training-day-absent) are missed by every model regardless of overall ROC-AUC; DDoS (also training-day-absent) fares better for Isolation Forest specifically. The fixed autoencoder now has the *best* ROC-AUC here (0.822) but still a near-zero calibrated recall — ranking ability and operating-point recall tell different stories.

**"Known-attack" split** (stratified within all 8 real day files, grouped into 2,000-row contiguous blocks — this mirror ships no Timestamp column at all, confirmed by reading the real header, so row order is used as the real temporal-adjacency proxy; 1,419 real windows, 426 assigned to test):

| Model | ROC-AUC (95% CI) | Recall@cal (1% FPR) |
|---|---|---|
| Isolation Forest | 0.727108 [0.720, 0.736] | 0.176634 |
| Autoencoder | 0.868278 [0.862, 0.872] | 0.100833 |
| LightGBM | 0.999983 [0.9999, 1.0] | 0.999984 |

LightGBM is essentially perfect at recognising attack types it has already seen within the same capture days (0.999983) but collapses to 0.753472 the moment the attack type is confined to a day outside training (the split above) — real, direct evidence that CICIDS2017's real difficulty for this platform's models is day-boundary generalisation, not within-distribution classification. (CICIDS2017's synthetic, repetitive attack generation likely also inflates the known-attack number somewhat — flagged as a real limitation of the dataset, not claimed as a clean causal estimate.)

### Corrected CICIDS2017 release (WTMC-2021) — now run, see Phase 1.6 below

Downloaded and run this session — superseded by the "Corrected CICIDS2017" subsection of Phase 1.6 below, which has the real comparison numbers.

### Real test counts (this session's CI, not estimated)

`main`@`d2b760c` (before this work): 1099 unit/contract passed, 174 integration passed (1 pre-existing flaky failure, unrelated). `feat/ml-detector-upgrade`@`b400600` (after Phase 1.5): 1109 unit/contract passed, 175 integration passed, 0 failures.

**After Phase 1.6** (`python -m pytest packages services tests -q -m "not integration"`, local): **1167 passed, 1 skipped (torch optional-dep guard), 175 deselected (integration-marked)**, 0 failures. The 175 integration tests themselves require Postgres/Kafka (`docker compose -f deploy/docker/docker-compose.yml up -d`) — not running on this machine, so locally they report skipped rather than passed; the real pass count for them comes from CI, which does start those services (confirmed green on the final push, below).

## Phase 1.6: split orientation, duplicates, base rates, corrected CICIDS2017, production integration

Run `20261012T1433-phase1.6-final`, commit `ee95b5a11f7e` (LightGBM integration) + this session's corrected-CICIDS2017 rerun and live-wiring/feature-compatibility audit, consolidated into one run-id. Full detail: `eval/reports/20261012T1433-phase1.6-final/{unsw_nb15_official_audit.json,inference_latency_benchmark.json,inference_latency_e2e_benchmark.json,partial_cicids2017_corrected.json,report.md}`.

### 1. Split orientation — UNSW-NB15's official files are reversed vs. their own filenames

Checked against the documented convention (Moustafa & Slay's own published partition sizes: 175,341 train / 82,332 test). This mirror's physical files are **reversed**: `UNSW_NB15_training-set.csv` has 82,332 rows, `UNSW_NB15_testing-set.csv` has 175,341 — a real data-quality bug in the `mrwellsdavid/unsw-nb15` Kaggle mirror, not something this project introduced. `load_unsw_nb15_official_split` now defaults to **`orientation="standard"`**, which picks train/test by matching real row counts against the documented sizes rather than trusting the filename — this is now the primary result everywhere in this report. `orientation="literal"` (the old, now-known-reversed behaviour) is kept only as a labelled secondary comparison.

| | Standard (primary) | Literal (secondary, reversed) |
|---|---|---|
| Train rows | 175,341 | 82,332 |
| Train attack prevalence | 0.680622 | 0.5506 |
| Test rows | 82,332 | 175,341 |
| Test attack prevalence | 0.5506 | 0.680622 |

**All three models, same primary split** (standard orientation, 82,332 test rows, attack prevalence 0.5506 — the no-skill PR-AUC baseline for the PR-AUC column):

| Model | ROC-AUC | PR-AUC (base rate 0.5506) | Recall@1%FPR |
|---|---|---|---|
| Isolation Forest | 0.781905 | 0.820115 | 0.214683 |
| Autoencoder | 0.772533 | 0.801370 | 0.240823 |
| LightGBM | 0.985255 | 0.989187 | 0.872673 |

Isolation Forest and the autoencoder are close to each other on every column (within ~0.01 ROC-AUC, ~0.02 PR-AUC) — neither is a clear second-best on this primary split — while LightGBM remains far ahead of both, consistent with its supervised advantage everywhere else in this report.

### 2. Duplicates — with and without test rows that exactly match a train row

Exact row-hash match on the real float32 feature vector (rounded to 6 decimals) — not fuzzy matching. Standard orientation: 1,295 of test's 53,939 unique rows (2.40%) are exact duplicates of a train row. This is a real property of the dataset's own official split, not something this project's code introduced, and the primary result above is reported **with duplicates left in** (the official split, as the authors shipped it). A labelled secondary rerun removes them:

| | With duplicates (primary) | Duplicates removed (secondary) |
|---|---|---|
| Test rows | 82,332 (prevalence 0.5506) | 73,791 (prevalence 0.518532) |
| Isolation Forest ROC-AUC | 0.781905 | 0.790510 |
| Autoencoder ROC-AUC | 0.772533 | 0.772808 |
| LightGBM ROC-AUC | 0.985255 | 0.982895 |
| LightGBM recall@calibrated threshold | 0.899034 | 0.881165 |

Real, small effect in both directions — duplicate removal does not meaningfully change the picture for any model; LightGBM's recall drops by ~1.8 points, Isolation Forest's ROC-AUC rises slightly. Not described as "fixed" — this is a measured sensitivity check, not a correction applied to the primary number.

### 3. Base rates — attack prevalence next to every test set's PR-AUC

| Dataset / split | Test rows | Attack prevalence (no-skill baseline) | Best PR-AUC |
|---|---|---|---|
| UNSW-NB15, official split (standard, primary) | 82,332 | 0.5506 | 0.989187 (LightGBM) |
| UNSW-NB15, official split (literal, secondary) | 175,341 | 0.680622 | 0.993491 (LightGBM) |
| UNSW-NB15, official split, duplicates removed | 73,791 | 0.518532 | 0.985835 (LightGBM) |
| CICIDS2017, Kaggle mirror, day-split (Mon-Thu→Fri) | 703,245 | 0.41078 | 0.781633 (LightGBM) |
| CICIDS2017, Kaggle mirror, known-attack split | 850,347 | 0.21554 | 0.99995 (LightGBM) |
| CICIDS2017, corrected (WTMC-2021), day-split (Mon-Thu→Fri) | 547,915 | 0.46813 | 0.945528 (LightGBM) |
| CICIDS2017, corrected (WTMC-2021), known-attack split | 631,749 | 0.22393 | 0.999929 (LightGBM) |

PR-AUC on every row above is well clear of its own no-skill baseline (the attack prevalence), so none of the strong PR-AUC numbers elsewhere in this report are an artefact of a near-100%-positive test set.

### 4. Corrected CICIDS2017 release (WTMC-2021) is now PRIMARY; the Kaggle mirror is secondary

The corrected release (`data/raw/cicids2017_corrected/`, direct download, no registration — see `data/README.md` for the source URL, licence, and per-file sha256s) fixes real, published errors (>20% of flows relabelled) that the Kaggle mirror used everywhere earlier in this report does not have. **From this point on, the corrected release is the primary CICIDS2017 result; the Kaggle mirror's original-label numbers are kept only as a labelled secondary comparison**, same convention as UNSW-NB15's standard/literal split above. Structurally different from the mirror: 5 files (one per capture day, no morning/afternoon split) instead of 8, and a real documented label correction (distinguishes `"Bot"` from `"Bot - Attempted"`, which the original release conflated). Same two splits rerun on it, train=Monday-Thursday/test=Friday for the day split (the corrected release's 5-file layout makes this an exact 4-file/1-file boundary, vs. the mirror's 6-file/3-file one — not a 1:1 identical split, flagged here rather than glossed over).

**Day-based ("unseen-attack generalisation") split — ROC-AUC / PR-AUC:**

| Model | Corrected (WTMC-2021, primary) ROC-AUC | Mirror (secondary) ROC-AUC | Corrected PR-AUC | Mirror PR-AUC |
|---|---|---|---|---|
| Isolation Forest | 0.749729 | 0.596546 | 0.640134 | 0.486772 |
| Autoencoder | 0.752310 | 0.821515 | 0.670575 | 0.608670 |
| LightGBM | 0.953734 | 0.753472 | 0.945528 | 0.739962 |

**Day-based split — recall at 1% FPR** (test-set attack prevalence: corrected 0.46813, mirror 0.41078 — see base-rate table above):

| Model | Recall@1%FPR, corrected (primary) | Recall@1%FPR, mirror (secondary) |
|---|---|---|
| Isolation Forest | 0.000168 | 0.000273 |
| Autoencoder | 0.000183 | 0.000021 |
| LightGBM | 0.388394 | 0.287025 |

**Day-based split — per-attack recall on the Friday held-out test day** (PortScan/DDoS/Bot are genuinely absent from the Monday-Thursday training days in both releases; the corrected release additionally splits `"Bot"` from `"Bot - Attempted"`, which the mirror conflates into one `Bot` label):

| Model | Bot recall, corrected | Bot recall, mirror | Bot-Attempted recall, corrected | DDoS recall, corrected | DDoS recall, mirror | PortScan recall, corrected | PortScan recall, mirror |
|---|---|---|---|---|---|---|---|
| Isolation Forest | 0.059621 | 0.022889 | 0.0 | 0.999474 | 0.635553 | 0.000540 | 0.001636 |
| Autoencoder | 0.059621 | 0.0 | 0.0 | 0.0 | 0.000422 | 0.000019 | 0.000044 |
| LightGBM | 0.0 | 0.001017 | 0.0 | 0.942306 | 0.185094 | 0.000547 | 0.001359 |

**Read honestly:** `"Bot - Attempted"` — the label the corrected release newly splits out — is missed completely (recall 0.0) by every model; the models fare somewhat better on the now-cleanly-labelled `"Bot"` itself. DDoS recall is strong for Isolation Forest and LightGBM on the corrected data (0.999/0.942) but PortScan stays near-zero for every model on both releases — a real, specific, attack-type-dependent generalisation gap, not a uniform failure.

**Known-attack (within-day) split:**

| Model | Corrected (primary) ROC-AUC | Mirror (secondary) ROC-AUC | Corrected PR-AUC | Mirror PR-AUC |
|---|---|---|---|---|
| Isolation Forest | 0.806498 | 0.727108 | 0.432076 | 0.491060 |
| Autoencoder | 0.805071 | 0.868278 | 0.423328 | 0.529246 |
| LightGBM | 0.999976 | 0.999983 | 0.999929 | 0.999500 |

**Read honestly:** LightGBM's day-split ROC-AUC jumps substantially on the corrected labels (0.753→0.954) — consistent with the corrected release's own claim of fixing >20% mislabelled flows: a supervised model trained on cleaner labels generalises better to an unseen day. Isolation Forest also improves on the corrected release in both splits. The autoencoder is mixed — slightly worse on the corrected day-split, moderately worse on known-attack — and every model's `recall_at_calibrated_threshold` on the corrected known-attack split for Isolation Forest/Autoencoder collapses to under 0.002 (vs. 0.18/0.10 on the mirror), a real, measured effect of calibrating a 1%-FPR threshold against a differently-balanced test set, not a regression in the models themselves. LightGBM stays essentially perfect on known-attack and far stronger on day-split with the corrected labels — the single clearest real improvement this comparison produced. **Every number in this report's other sections that referred to "CICIDS2017" without specifying a release should now be read as the mirror (secondary); this subsection's "corrected (primary)" columns are the ones to cite going forward.**

### 5. Production integration — served, but **not wired into live detection, and not fed real live features**

Confirmed first, not assumed: before this session, `ModelRegistry.load()` only dispatched `isolation_forest`/`mad_zscore` — a `gradient_boosting`-method artifact would hit the registry's final "cannot serve method" raise even if catalogued. Fixed in `ee95b5a`:

- `ModelRegistry` gained `gradient_boosting` dispatch, gated behind `SM_ML_ENABLE_GRADIENT_BOOSTING` (real env var, **off by default**). Flag off → the model is excluded from `available()` entirely; `ml-inference` behaves exactly as it did before this model existed. The existing ADR-013 degrade-to-`ModelUnavailable`/503 path needed no new code.
- A **new** model was trained for this — `scripts/train_gradient_boosting_network_flow.py`, on the platform's real 8-dim `NetworkFlowPayload` schema (`sm_ml.features.extract_features`, NSL-KDD replay). This is explicitly **not** the same model as the Phase 1/1.5/1.6 CICIDS2017/UNSW-NB15 78/193-dim benchmark LightGBM above — that model was never trained for the production feature space and couldn't be served through it. Real held-out result (`KDDTest+.txt`): precision 0.959, recall 0.712.
- Model card: `docs/models/gradient_boosting_network_flow.md`. Contract tests: `ml-inference/tests/test_infer.py` (catalog exclude/include + `/infer` 503-vs-200 on the flag), `ml-py/tests/test_registry.py`.

**Checked directly against the real code, not assumed either way — two separate real gaps, both documented in full in the model card:**

1. **`detection-engine` never requests this model, flag or no flag.** `inference_client.py`'s `MODEL_FOR_KIND` hardcodes `network_flow -> "isolation_forest_network_flow"`. The flag only makes `ml-inference` willing to *serve* `/infer/gradient_boosting_network_flow` if called directly (which is what both latency benchmarks below do) — it does not route any real detection-flow traffic to this model.
2. **This repo's only real end-to-end event producer (`simulation-service`) feeds it mostly-constant input.** Checked feature-by-feature against `sm_simulation_service/pipeline.py` and `extract_features`: 6 of the model's 8 real feature dimensions (`bytes_received_log`, `packets_total_log`, `dst_port`, `dst_port_is_system`, `dst_port_is_ephemeral`, `proto_tcp`) are degenerate constants (always 0 or always 1) for every simulated event this platform actually generates — `services/ingestion-gateway` *could* carry full real features from a genuine external flow collector, but no such collector is built or deployed here. Full per-feature table: `docs/models/gradient_boosting_network_flow.md`.

**Conclusion: this model is an offline benchmark result only, not a live detector.** Both gaps must close (real routing in `detection-engine`, and real non-degenerate input — either a real collector or a richer simulation payload) before `SM_ML_ENABLE_GRADIENT_BOOSTING` should ever be turned on outside a benchmark. It stays off by default. The CICIDS2017/UNSW-NB15 numbers throughout this report are a genuine offline evaluation of the model's learning capability — they are not a claim about what SentinelMesh detects live today.

**Real CPU latency/throughput — two different things, measured separately and not interchangeable:**

**(a) In-process, `scripts/benchmark_inference_latency.py`** — calls `GradientBoostingModel.score()` / `Booster.predict()` directly in a bare Python loop. Real NSL-KDD rows through the real `extract_features` path, this machine (AMD Ryzen 7 6800H, CPU-only), but **bypasses the FastAPI app entirely** — no routing, no auth, no pydantic validation, no `ModelHost` lookup:

| | p50 | p99 | Throughput |
|---|---|---|---|
| Single call (`model.score()`, one row at a time) | 0.147 ms | 0.452 ms | 6,090.5 flows/s |
| Batch of 1,000 (`Booster.predict()`, one real vectorised call) | 2.43 ms | 3.37 ms | 411,234.9 flows/s |

**(b) End-to-end through the real service API, `scripts/benchmark_inference_latency_e2e.py`** — builds the real `sm_ml_inference` FastAPI app (`create_app`) and drives real `POST /api/v1/infer/gradient_boosting_network_flow` calls through `fastapi.testclient.TestClient`: real routing, real internal-JWT auth, real pydantic request/response validation, the real `ModelHost`/`ModelRegistry` lookup, real model scoring, real response serialization — everything `/infer` actually does in production **except the OS network socket/TCP hop itself** (`TestClient` uses httpx's in-process ASGI transport, not a real deployed network path):

| | p50 | p99 | Throughput |
|---|---|---|---|
| Single request | 3.64 ms | 4.70 ms | 269.5 req/s |
| "Batch" of 1,000 (**no batch endpoint exists** — `InferRequest.features` is one flow's vector, not a list; this is 1,000 real sequential HTTP calls to the same single-flow endpoint) | 3.60 ms | 4.62 ms | 272.0 req/s |

**Read honestly:** (a) and (b) are not the same measurement and do not agree — (b) is ~25x slower at p50 for a single request, because it includes real FastAPI routing, middleware, auth-token verification, and pydantic validation that (a) skips entirely; that gap is the real, measured cost of the parts of the request path (a) doesn't exercise. (b)'s "batch" number is nearly identical to its single-request number because **no batch endpoint exists in the real API** — the ~67x speedup (a) shows for batching only applies to a direct in-process `Booster.predict()` call on a pre-assembled array, not to anything the real `/infer` endpoint can currently do for 1,000 separate flows. Full reports: `eval/reports/20261012T1433-phase1.6-final/{inference_latency_benchmark.json,inference_latency_e2e_benchmark.json}`.
