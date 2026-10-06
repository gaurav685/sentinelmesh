# NSL-KDD graph derivative (for GNN training)

**Status: VERIFIED (real, executed, built from real NSL-KDD rows).**

Built by `scripts/build_graph_dataset_nsl_kdd.py` because CICIDS2017 and UNSW-NB15 (the preferred datasets for this, per the remediation prompt) are both BLOCKED — see `docs/datasets/cicids2017.md`, `docs/datasets/unsw_nb15.md`, `docs/PRIORITY_REMEDIATION_PLAN.md`. The repository owner confirmed training on NSL-KDD now rather than blocking GNN work entirely.

## Source

- `KDDTrain+.txt` → `ml/datasets/nsl-kdd-graph/train.jsonl` (sha256 `1b86d2f957b33082081bba410fe129b475efebcc13c9014c3f447c8271aadf95` source; `b36c68c885c71b994464d7f16866caca3d58a44d332aa774ba5cbdbece8aae79` derived output)
- `KDDTest+.txt` → `ml/datasets/nsl-kdd-graph/test.jsonl` (sha256 `fa46b0935342616aa83b7c2578db355b6a7aaabbc492248172c7a1e8b7ab8f84` source; `f2a21a16e150f2179b3152b84e329c0327d6dae64d9181b0ca2ff3b649ae72d3` derived output)

## Construction (deterministic, from real rows)

NSL-KDD carries no real IP addresses or graph structure of its own. Each row's source becomes one `IpAddress` node with a synthesized id (`10.50.<row//256>.<row%256>`), identical to the scheme `scripts/ingest_nsl_kdd.py` already uses for the real ingestion pipeline. Each row's destination is one of 16 fixed `IpAddress` hub nodes (`10.60.0.1`..`10.60.0.16`), also the same fixed pool. A `CONNECTED_TO` edge links source to destination. Rows are grouped into fixed-size windows (500 rows) — one graph sample (one JSON line) per window.

- Train: 252 samples, 130,005 total nodes, 58,630 attack-labelled nodes
- Test: 46 samples, 23,280 total nodes, 12,833 attack-labelled nodes

## Labels

- A source node's label is the row's real NSL-KDD ground truth (0 = normal, 1 = any attack type) — never fabricated.
- A destination hub's label is always 0: under this star topology, a hub represents shared destination infrastructure (a server), not an attacker. This is a stated modeling choice, not a hidden one.

## Known, important limitation (see `docs/ML_BENCHMARK_REPORT.md` for the measured consequence)

Every source node has degree exactly 1 (one edge, to its one destination hub). `sm_ml.graph.construct.build_graph_sample`'s node features are purely structural (degree, clustering coefficient, temporal position, node-type one-hot) by design — the right feature set for the platform's real, richly-connected live attack graph, but it means this derivative's structural features cannot distinguish an attack row from a benign one: both get identical degree-1, single-neighbor structural features. NSL-KDD's actual discriminative signal (connection duration, byte counts, protocol) never reaches the GNN through this construction. The real GraphSAGE/GAT training and evaluation pipeline built against this dataset is genuine, working code — the dataset itself is simply not a good fit for demonstrating a graph model's advantage. A real multi-hop topology (CICIDS2017/UNSW-NB15 with real IP relationships, or the platform's own live-ingested attack graph) is the right test of that.
