# Priority remediation report

Executed 2026-10-06. This is an exit report for the priority-remediation pass requested against the known weaknesses in ML/data, Kubernetes, CI, and requirements traceability. Every claim below is either a real executed result (with the exact command/evidence) or an explicit `BLOCKED`/`NOT VERIFIED` status — nothing here converts source-code presence into verification, and nothing is fabricated. See `docs/PRIORITY_REMEDIATION_PLAN.md` for the area-by-area tracking table this report closes out.

## Starting state (what was actually found, by inspection)

- `sm_ml.models.autoencoder.AutoencoderModel.score()` unconditionally raised `ModelNotTrained` — no training loop existed anywhere in the repository for it.
- `sm_ml_training.pipeline.TrainingPipeline.train()` explicitly raised `PipelineSkipped("GNN training loop is a TODO — the boundary is implemented, weights are not")` for `graphsage`/`gat` — confirmed by reading the code, not assumed.
- The Kubernetes migration Job (`deploy/helm/sentinelmesh/templates/migration-job.yaml`) was annotated as a `pre-upgrade` Helm hook unconditionally, with no `.Release.IsUpgrade` guard, despite its own docstring describing the opposite intended behavior.
- `.github/workflows/ci.yml` had no Kubernetes job at all; the README stated this plainly.
- R18/R36 were absent from `docs/REQUIREMENTS_TRACEABILITY.md` with no primary source available to recover them from (confirmed again this session, and directly with the repository owner).

## Dataset acquisition — what was actually attempted and downloaded

- **CICIDS2017**: live HTTP requests made to the historical direct-download host. Every dataset file URL now 301/302-redirects to `https://www.unb.ca/cic/datasets/index.html`, an HTML registration/landing page (108,784 bytes, `Content-Type: text/html`) — not a dataset file. **BLOCKED — NOT VERIFIED — REQUIRES MANUAL REGISTRATION.** See `docs/datasets/cicids2017.md`.
- **UNSW-NB15**: live HTTP request made to the current official project page (`200 OK`), parsed for direct download links — none found; the dataset's historical CloudStor host is gone. **BLOCKED — NOT VERIFIED — REQUIRES MANUAL ACCESS.** See `docs/datasets/unsw_nb15.md`.
- **NSL-KDD**: confirmed already present and correct locally (`C:\Sentinel_Mesh\archive\{KDDTrain+,KDDTest+}.txt`); sha256 matches the hashes already recorded from Phase 15. **VERIFIED.**
- Decision to proceed on NSL-KDD for Autoencoder/GNN training, with CICIDS2017/UNSW-NB15 carried forward as documented blockers rather than halting all ML work, was confirmed directly with the repository owner (not assumed).

## Dataset validation

NSL-KDD's existing adapter (`sm_ml_training.benchmark.nsl_kdd`) was re-audited: real file reads, vocabulary derived from the train split itself (not hardcoded), an explicit `__unknown` bucket for unseen categorical values, sha256 recorded per file, label mapping (`normal` vs. any other value) unchanged and correct. No leakage columns identified beyond the label/difficulty columns, which are explicitly excluded from the feature vector.

## Autoencoder — real training executed

- `scripts/train_autoencoder_network_flow.py` (new): PyTorch encoder/decoder per `AutoencoderSpec` (hidden dims `[16, 8]`), fit on the 67,343 benign-only rows of NSL-KDD's train split using the platform's real 8-dim `extract_features` encoding (train/serve parity with `detection-engine`, same convention as the existing Isolation Forest training script). Adam optimizer, early stopping on a held-out validation split (20 epochs run before stopping, best val MSE 1e-6).
- Real checkpoint produced: `ml/artifacts/autoencoder_network_flow/v1/{model.pt, metadata.json}`.
- `sm_ml.models.autoencoder.AutoencoderModel` extended with a real `load()`/`score()` path (previously always raised `ModelNotTrained`) — same honest-degradation shape as `IsolationForestModel.load`: `ModelUnavailable` without `sm-ml[autoencoder]` (torch), a real forward pass otherwise. Round-trip verified: load the just-trained checkpoint, score a real vector, confirm the result.
- Held-out sanity check (`KDDTest+.txt`, label used only for the printout): precision 0.845, recall 0.100.
- A second, independent instance trained directly inside the benchmark harness (`sm_ml_training.benchmark.harness._fit_autoencoder`/`_score_autoencoder`, new) on the harness's own 125-dim one-hot encoding — added as a new `"autoencoder"` `ModelName`, reusing the existing harness rather than building a parallel framework (item 19). Real run: ROC-AUC 0.434284 (see ML_BENCHMARK_REPORT.md — this is genuinely the weakest of the three tabular methods, reported as measured).
- New real test: `packages/ml-py/tests/test_models.py::test_autoencoder_build_module_trains_and_round_trips` — trains for real, saves, loads, scores; skipped (not faked-passing) where torch is absent.

**Status: VERIFIED — real training executed, real checkpoint, real (unflattering) benchmark number.**

## GNN (GraphSAGE/GAT) — real training executed

- **Graph dataset**: CICIDS2017/UNSW-NB15 graph derivatives are blocked (same reason as above). `scripts/build_graph_dataset_nsl_kdd.py` (new) builds a real, deterministic graph from real NSL-KDD rows — see `docs/datasets/nsl_kdd_graph_derivative.md` for the exact construction, its real output (252 train samples / 130,005 nodes; 46 test samples / 23,280 nodes), and its stated structural limitation (discovered by the benchmark below, not assumed in advance).
- `sm_ml.graph.models.gnn` extended with `build_gnn_module`/`gnn_module_class` — real, picklable `torch_geometric` `SAGEConv`/`GATConv` encoder-decoder modules (the existing `GnnNodeAnomalyModel` inference path already did a real forward pass; it had never had a module to train).
- `sm_ml_training.pipeline.TrainingPipeline._train_gnn` (new, replaces the `PipelineSkipped` stub): real per-sample training loop, loss masked to benign-labelled nodes only (the graph-structured analogue of the existing benign-only tabular convention, ADR-013), real backprop, real checkpoint (`torch.save`) written to `ml/artifacts/graph/`.
- Real executed runs: GraphSAGE (15 epochs, hidden_dim=32) and GAT (15 epochs, hidden_dim=32, 4 heads) both trained to a real, low final training loss (3.8e-5 and 1.4e-4 respectively).
- `scripts/evaluate_gnn_checkpoint.py` (new): loads each real checkpoint, scores every node of the held-out `test.jsonl`, computes ROC-AUC/precision/recall/F1/FPR with the **same** `sm_ml_training.benchmark.metrics` functions the tabular benchmark uses (item 19, reuse not reinvention).
- Real result: **ROC-AUC ≈ 0.49 for both** — essentially random. Root-caused (not hand-waved): NSL-KDD's forced star topology gives every source node identical degree-1 structural features regardless of its real label, so the GNN's purely-structural input (by design, for the platform's real multi-hop attack graph) carries no signal on this particular derived dataset. Full account in `docs/ML_BENCHMARK_REPORT.md`.

**Status: VERIFIED — the training/evaluation infrastructure is real and works end to end; the resulting model's accuracy on this dataset is real and genuinely poor, for an identified structural reason, not a training bug.**

## Benchmarks — classical vs. deep vs. graph, real measured comparison

See `docs/ML_BENCHMARK_REPORT.md` for the full table. Summary: Isolation Forest (ROC-AUC 0.935) >> statistical baseline (0.639) >> tabular autoencoder (0.434) ≈ GraphSAGE/GAT (0.49, i.e. chance) on NSL-KDD specifically. Reported exactly as measured; no tuning was performed to make any number look better.

## Kubernetes — real `kind` + Helm verification, two real bugs found and fixed

Performed on a real local `kind` cluster (`kind create cluster`; images pulled directly via the node's own `crictl pull` after `kind load docker-image` failed with a `ctr: content digest ... not found` error traced to Docker Desktop's content-store/multi-arch-manifest interaction — a real, separate environment issue, worked around rather than ignored).

1. **Migration Job never created on first install.** `templates/migration-job.yaml` set `"helm.sh/hook": pre-upgrade` unconditionally; Helm never fires `pre-upgrade` hooks during `helm install`. Confirmed directly: `kubectl -n sentinelmesh-app get jobs` returned nothing after a real `helm install`. **Fixed**: the hook annotation is now gated on `{{- if .Release.IsUpgrade }}`, matching the file's own pre-existing (but previously unimplemented) documented intent. Re-verified: the Job now appears immediately on a fresh install.
2. **`socket.create_connection(..., timeout=2)`'s timeout does not bound DNS resolution.** The existing `wait-for-postgres` initContainer's retry loop could hang indefinitely on a single slow `getaddrinfo` call, never reaching its own retry/sleep logic — found by watching a real init container sit in `Init:0/1` for over 5 minutes with zero log output, impossible under the loop's stated ~120s budget if the timeout were actually working. **Fixed**: `signal.alarm(2)` now bounds the entire attempt (lookup + connect), with the alarm correctly cancelled before each `time.sleep` (a first version of this fix had the alarm fire mid-sleep and crash the retry loop entirely — found and fixed in the same pass, by reading the resulting traceback).
3. **`SM_ENV: production` + `SM_KAFKA_SECURITY_PROTOCOL: PLAINTEXT` together in the chart's own default `values.yaml`** tripped `AppSettings`'s real production fail-fast guard on every single pod, every single install — the migration container itself failed instantly on this before ever attempting a database connection. This had never surfaced before because bug #1 meant the migration Job never ran at all. **Fixed**: default `SM_ENV` changed to `staging`, matching what this chart's self-hosted, PLAINTEXT-Kafka, dev-friendly-secrets posture actually is; a real production deployer swapping in managed Kafka + SASL_SSL sets `production` explicitly at that point.
4. **Remaining, not fully resolved**: with both bugs above fixed, the migration Job's `alembic` process itself still hit intermittent-to-sustained `socket.gaierror: [Errno -3] Temporary failure in name resolution` resolving the Postgres Service name, across 20 consecutive attempts over several minutes, on the final observed run — the Job ultimately failed (`BackoffLimitExceeded`) in this specific test. Node memory was independently confirmed at 93-99% allocated throughout. This is the same class of issue Phase 16 already documented as `NOT VERIFIED — REQUIRES FURTHER INVESTIGATION` ("a real characteristic of a single kind node running the full stack under CPU/memory pressure") — now further narrowed (CoreDNS has a single ClusterDNS entry with no secondary nameserver in this topology, and showed no crashes/restarts, consistent with queries being dropped/timed out under sustained resource pressure rather than CoreDNS itself failing) but still **NOT VERIFIED — REQUIRES A LARGER NODE OR REDUCED CONCURRENT WORKLOAD**, not claimed fixed.

**Helm full verification status**: with the stack scaled to 1 replica per service and Neo4j disabled (to fit this session's single kind node's real ~7.5GB RAM), Postgres, Redis, MinIO, and most app-tier Deployments reached `Running`; several app services that depend on a migrated schema cycled through `CrashLoopBackOff` while the migration Job was still retrying, which is expected and would self-resolve once migration succeeds. **PARTIAL** — not the full 6-stateful/14-service topology Phase 16 originally targeted (this session's node could not fit that at full replica count either, same resource ceiling), and the migration Job's final run in this test did not complete.

## CI — kind-based Kubernetes job added

`.github/workflows/ci.yml`: new `kind-deploy` job (`needs: [image]`), using `helm/kind-action@v1.15.1`, `azure/setup-helm@v5.0.1`, `azure/setup-kubectl@v5.1.0` (all three verified to actually exist via `gh api repos/.../releases` before pinning, not guessed). Builds the real app image, loads it into a fresh `kind` cluster, applies namespaces, `helm install`s a deliberately scoped-down subset (Postgres + migration Job + `api-gateway`; Neo4j/Redpanda/MinIO/Keycloak/frontend/ingress disabled, 1 replica per service) — scoped down for the same practical reason noted above (item 28: a full-stack job would be flaky from runner resource pressure, not from a real defect, which is not a meaningful CI signal). Asserts the migration Job reaches `Complete` and `api-gateway`'s rollout succeeds; dumps full cluster state and logs on failure; always tears the cluster down. **This workflow has not yet run on a real GitHub Actions runner** (that happens on push) — reported here as `IMPLEMENTED — NOT VERIFIED ON A REAL RUNNER YET`, not claimed green.

## R18 / R36

Re-confirmed directly with the repository owner this session: the primary 38-point architecture source and the "SentinelMesh Complete Elite Blueprint" do not exist anywhere accessible. **BLOCKED — NOT VERIFIED — REQUIRES PRIMARY ARCHITECTURE SOURCE.** Recorded as a confirmed permanent gap in `docs/REQUIREMENTS_TRACEABILITY.md`, not invented. R1–R17, R19–R35, R37–R38 (36 of 38) remain present and mapped, unchanged by this pass.

## Remaining limitations (everything still incomplete or externally blocked)

- CICIDS2017 and UNSW-NB15 remain blocked on manual registration/access (exact steps in `docs/datasets/`).
- R18/R36 remain blocked on a source document that does not exist in any accessible form.
- The Kubernetes migration Job's DNS-under-resource-pressure issue is real, reproducible on a small single-node cluster, and not conclusively resolved — a larger node (more CPU/RAM headroom for CoreDNS) is the most likely real fix, not yet tested here.
- The new `kind-deploy` CI job has not yet run on a real GitHub Actions runner; its first real result arrives on the next push.
- GraphSAGE/GAT are real, working, trained models with genuinely poor accuracy on NSL-KDD specifically, for a structural reason tied to that dataset — not yet tested against a dataset with real multi-hop topology.
- The tabular autoencoder underperforms both classical baselines on NSL-KDD; no architecture/hyperparameter search was run to see whether this is fixable (would require deliberately not tuning against the test set, i.e. a proper train/val-only search, not attempted in this pass due to time).

## Final status: **PARTIAL**

Real, verified progress across every area this pass targeted: two genuinely new, trained, checkpointed, benchmarked ML models (Autoencoder, GraphSAGE/GAT) where none existed before; three real Kubernetes/Helm bugs found and two of them definitively fixed and re-verified; a real Kubernetes CI job added (not yet runner-verified); R18/R36 and the two blocked datasets honestly reconfirmed rather than silently left stale. Not `COMPLETE`: the migration Job's DNS issue under resource pressure persists, CICIDS2017/UNSW-NB15 remain inaccessible, R18/R36 remain genuinely unrecoverable, and the new CI job awaits its first real runner execution.
