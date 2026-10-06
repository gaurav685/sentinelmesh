# ML benchmark report

Real, executed runs only. Every number below came from an actual `python -m sm_ml_training benchmark` / `scripts/evaluate_gnn_checkpoint.py` invocation against the real, locally-staged NSL-KDD files; raw output is committed under `artifacts/benchmarks/nsl_kdd/*.json`. Nothing here was estimated, illustrative, or hand-typed without a corresponding run. Where a run wasn't executed, the row says `N/A — NOT RUN` rather than a guessed number.

## Dataset

**NSL-KDD** (`KDDTrain+.txt`, 125,973 rows; `KDDTest+.txt`, 22,544 rows, 12,833 anomalous). Train sha256 `1b86d2f957b33082081bba410fe129b475efebcc13c9014c3f447c8271aadf95`; test sha256 `fa46b0935342616aa83b7c2578db355b6a7aaabbc492248172c7a1e8b7ab8f84` (same files as Phase 15's original benchmark — continuity preserved).

**CICIDS2017** — BLOCKED. Live-checked 2026-10-06: the dataset's direct-download host now redirects to a registration/request page at UNB, with no anonymous download path. See `docs/PRIORITY_REMEDIATION_PLAN.md` and `docs/datasets/cicids2017.md` for the exact manual steps.

**UNSW-NB15** — BLOCKED. Live-checked 2026-10-06: the dataset's AARNet CloudStor host is gone; the current official page carries no working direct download link. See `docs/datasets/unsw_nb15.md`.

Both were investigated and genuinely attempted (not merely assumed unavailable) before being marked blocked; see the Datasets section of `docs/PRIORITY_REMEDIATION_PLAN.md` for the exact HTTP responses observed.

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

**Overall, honest conclusion:** on NSL-KDD specifically, classical ML (Isolation Forest) is the best-performing anomaly detector this project has measured, substantially ahead of both the deep tabular autoencoder and the graph neural networks. This does not mean deep/graph learning has no place in this platform — it means NSL-KDD, a 1999-era single-connection-record dataset with no real topology, is a poor fit for methods whose advantage is specifically learning from richer structure (correlated feature groups, multi-hop relationships) that this dataset does not provide. CICIDS2017/UNSW-NB15, once accessible (see blockers above), are the natural next test of that hypothesis.
