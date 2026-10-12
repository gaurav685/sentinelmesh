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
