# Requirements Traceability — SentinelMesh 38-Point Architecture

Every requirement 1–38 appears. Each maps:
Requirement → Purpose → Subsystem → Service → Module/File → Database → API →
Event → Frontend → ML/AI → Infrastructure → Security boundary → Test →
Verification method → Phase → Status.

`N/A — NOT REQUIRED BY ARCHITECTURE` is stated explicitly where a field does not
apply. No field is silently omitted.

**Global status note.** As of Phase 0 (2026-09-08) the system has **no runtime
implementation**. Every requirement's Status is `ARCHITECTURE DEFINED` unless a
narrower state is given. `Verification method` describes how the requirement
*will* be verified; none has been executed. No performance, latency, accuracy, or
deployment claim exists.

Status vocabulary: `ARCHITECTURE DEFINED` · `PARTIALLY IMPLEMENTED` ·
`IMPLEMENTED` · `LOCALLY VERIFIED` · `INTEGRATION VERIFIED` ·
`EXTERNALLY DEPENDENT` · `NOT VERIFIED`.

Phase map: P1 Foundation · P2 Telemetry+Normalization · P3 Graph+Detection+MITRE+TI ·
P4 Attack-chain+Lateral+Temporal+UI · P5 ML/GNN+Benchmark · P6 AI analyst+Memory+
Predictive+Explanation+NL hunting+RCA · P7 Multi-agent+Autonomous response ·
P8 Reporting+Observability dashboards+Docs · P9 Deception+Simulation+Digital twin ·
P10 Federated mesh · P38 Enterprise deployment hardening (runs across late phases).

---

### R1 — Telemetry Ingestion Layer
- **Purpose:** accept network/auth/DNS/process/file telemetry from sensors into a unified pipeline.
- **Subsystem:** Ingestion.
- **Service:** `ingestion-gateway` (+ `normalization-engine` boundary).
- **Module/File:** `services/ingestion-gateway/`, envelope in `packages/contracts-py/.../events`.
- **Database:** Postgres `sensor` (read); Redis (rate-limit, dedup). No durable writes.
- **API:** `POST /api/v1/ingest/{source_type}` (per-sensor auth); size/rate limited.
- **Event:** produces `telemetry.raw` (payloads `telemetry.network_flow|auth_event|dns_query|process_exec|file_access` v1).
- **Frontend:** sensor-management screens (list/register/rotate) — P8.
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **Infrastructure:** Kafka (Redpanda local), Redis.
- **Security boundary:** TB-1 (untrusted sensors); `tenant_id` bound to sensor identity, never trusted from body.
- **Test:** contract tests on envelope; security tests (bad credential, wrong-tenant payload, oversize, rate limit fail-closed); integration test sensor→topic.
- **Verification method:** integration test against Redpanda in docker-compose.
- **Phase:** P2. **Status:** ARCHITECTURE DEFINED.

### R2 — Event Normalization Engine
- **Purpose:** raw → canonical: schema standardization, Geo-IP, hostname resolution, user-device linking, threat-intel enrichment, cross-session identity stitching.
- **Subsystem:** Normalization.
- **Service:** `normalization-engine`.
- **Module/File:** `services/normalization-engine/` (`normalize/`, `enrich/`, `identity/`).
- **Database:** Postgres `identity_link`, `asset` (read); Redis (geoip/TI cache).
- **API:** internal only (`/healthz`, `/readyz`); enrichment consumed from `threat-intel-service`.
- **Event:** consumes `telemetry.raw`; produces `events.canonical` (`event.canonical` v1); DLQ `telemetry.raw.dlq`.
- **Frontend:** N/A (pipeline internal); enrichment provenance visible in event detail — P4.
- **ML/AI:** N/A (deterministic enrichment). Identity stitching is heuristic/rule-based here; ML linkage is future.
- **Infrastructure:** Kafka, Redis, MaxMind GeoLite2 file.
- **Security boundary:** TB-4 (outbound TI via service); tenant preserved on every output event.
- **Test:** unit (normalizers per source type, enrichment skip paths), integration (raw→canonical), contract (canonical schema).
- **Verification method:** integration test; golden-file normalization tests using dataset samples.
- **Phase:** P2. **Status:** ARCHITECTURE DEFINED.

### R3 — Graph Construction Engine
- **Purpose:** build a dynamic attack graph — multi-hop relationships, real-time evolution, attack-path optimization.
- **Subsystem:** Graph.
- **Service:** `graph-service` (sole Neo4j writer).
- **Module/File:** `services/graph-service/` (`commands/`, `query/`, `gds/`).
- **Database:** Neo4j (operational graph); Postgres `asset`/`identity` (attribute source).
- **API:** internal graph-query API; exposed to UI via `api-gateway`.
- **Event:** consumes `graph.commands`; produces `graph.events`.
- **Frontend:** live attack-graph view (R13, R25) — P4.
- **ML/AI:** GDS pathfinding/centrality feed R11 features; not a model itself.
- **Infrastructure:** Neo4j 5 + GDS, Kafka.
- **Security boundary:** internal; tenant property on every node/edge; no cross-tenant relationship (graph invariant).
- **Test:** unit (command→Cypher, idempotency), integration (Neo4j container), invariant tests (no cross-tenant edge).
- **Verification method:** integration tests against Neo4j container; invariant assertions.
- **Phase:** P3. **Status:** ARCHITECTURE DEFINED.

### R4 — Dynamic Graph Update System
- **Purpose:** streaming graph updates, temporal synchronization, real-time attack-state updates.
- **Subsystem:** Graph / Stream.
- **Service:** `stream-processor` (`graph-update-emitter`) + `graph-service` (apply).
- **Module/File:** `services/stream-processor/jobs/graph-update-emitter/`, `services/graph-service/commands/`.
- **Database:** Neo4j; Flink checkpoints (S3).
- **API:** N/A (event-driven).
- **Event:** `events.canonical` → `graph.commands` → applied; ordering per partition; idempotent by `command_id`.
- **Frontend:** graph deltas pushed via `notification-service` — P4.
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **Infrastructure:** Flink/Kafka/Neo4j/Redis fan-out.
- **Security boundary:** internal; per-key tenant isolation in stream state.
- **Test:** ordering/idempotency/replay tests; recovery test (kill job, restore from checkpoint).
- **Verification method:** integration test with induced failure + replay.
- **Phase:** P3–P4. **Status:** ARCHITECTURE DEFINED.

### R5 — Anomaly Detection Engine
- **Purpose:** Isolation Forest, autoencoders, behavioral analytics, adaptive thresholds.
- **Subsystem:** Detection / ML.
- **Service:** `detection-engine` (orchestration) + `ml-inference` (serving) + `ml-training`.
- **Module/File:** `ml/models/{isolation_forest,autoencoder}/`, `ml/features/`, `services/detection-engine/scoring/`.
- **Database:** Postgres `anomaly`, `threat_score`; MLflow registry; S3 artifacts.
- **API:** internal inference API (`ml-inference`); `detection-engine` consumes.
- **Event:** consumes `events.canonical` + `features.derived`; produces `detections`.
- **Frontend:** anomaly list, score visualizations — P4.
- **ML/AI:** IsolationForest (sklearn), autoencoder (PyOD/PyTorch); adaptive thresholds via rolling quantiles; **no accuracy claimed** — `NOT VERIFIED — REQUIRES REAL DATA / TRAINING ENVIRONMENT`.
- **Infrastructure:** MLflow, S3, (GPU for training — external).
- **Security boundary:** input validation / OOD rejection; model artifacts loaded only from trusted registry.
- **Test:** pipeline unit tests, reproducibility test, inference-failure fallback test, evaluation harness (metrics only after real run).
- **Verification method:** benchmark harness on UNSW-NB15/CICIDS2017/NSL-KDD with logged metrics — not yet run.
- **Phase:** P5. **Status:** ARCHITECTURE DEFINED.

### R6 — Attack Chain Detection
- **Purpose:** kill-chain reconstruction, AI attack-sequence inference, multi-stage/lateral/credential-escalation/exfiltration path detection.
- **Subsystem:** Detection / Stream / Graph.
- **Service:** `stream-processor` (`attack-chain-correlator`) + `detection-engine`.
- **Module/File:** `services/stream-processor/jobs/attack-chain-correlator/`, `services/detection-engine/chains/`.
- **Database:** Postgres `attack_chain`, `attack_chain_stage`; Neo4j `:AttackChain` + `:HAS_STAGE`.
- **API:** chain detail via `api-gateway` → `detection-engine`/`graph-service`.
- **Event:** consumes `events.canonical` + `detections`; produces `attack_chains`.
- **Frontend:** attack-chain timeline / multi-stage APT view — P4.
- **ML/AI:** sequence inference: rule + graph-pattern first; ML sequence model future (traced, not required for MVP).
- **Infrastructure:** Flink keyed session state, Kafka, Neo4j, Postgres.
- **Security boundary:** internal; tenant-keyed state.
- **Test:** scenario tests (synthetic multi-stage sequences → expected chain), lateness/out-of-order tests.
- **Verification method:** deterministic scenario fixtures + integration.
- **Phase:** P4. **Status:** ARCHITECTURE DEFINED.

### R7 — MITRE ATT&CK Integration
- **Purpose:** technique mapping, ATT&CK heatmaps, campaign alignment, technique confidence, versioning.
- **Subsystem:** Threat Knowledge.
- **Service:** `mitre-service`.
- **Module/File:** `services/mitre-service/` (`catalog/`, `mapping/`), `scripts/import_attack_stix.py`.
- **Database:** Postgres `attack_tactic`, `attack_technique`, `attack_matrix_version`, `technique_mapping`.
- **API:** `GET /api/v1/mitre/techniques`, `.../heatmap`, mapping internal API.
- **Event:** consumes `detections`/`attack_chains` (mapping triggers); no dedicated topic.
- **Frontend:** ATT&CK heatmap component — P4/P8.
- **ML/AI:** mapping is rule/graph/feature-based; optional LLM-assisted mapping via `ai-analyst-service` with confidence, never authoritative alone.
- **Infrastructure:** offline STIX bundle import.
- **Security boundary:** catalog global; mappings tenant-scoped.
- **Test:** catalog import test, mapping unit tests, `UNMAPPED` handling.
- **Verification method:** import a pinned ATT&CK version, assert catalog counts; mapping fixtures.
- **Phase:** P3. **Status:** ARCHITECTURE DEFINED.

### R8 — Threat Scoring Engine
- **Purpose:** deterministic composite risk score, dynamic confidence, prioritization.
- **Subsystem:** Detection.
- **Service:** `detection-engine` (`scoring/composite.py`).
- **Module/File:** `services/detection-engine/scoring/`.
- **Database:** Postgres `threat_score` (inputs + weights + output persisted for auditability).
- **API:** score included in detection responses via `api-gateway`.
- **Event:** part of `detections` payload.
- **Frontend:** risk heatmaps, prioritized alert queue — P4.
- **ML/AI:** inputs may include ML anomaly scores; the **combination is deterministic** (documented weights/formula, versioned). No validated scoring performance claimed.
- **Infrastructure:** Postgres.
- **Security boundary:** internal; tenant-scoped.
- **Test:** deterministic scoring unit tests (fixed inputs → fixed output), weight-version tests, degradation tests (missing input).
- **Verification method:** unit tests with golden vectors.
- **Phase:** P3. **Status:** ARCHITECTURE DEFINED.

### R9 — Threat Intelligence Engine
- **Purpose:** IOC integration, threat-actor enrichment, TI fusion, reputation scoring, freshness/expiry/provenance, provider-failure tolerance.
- **Subsystem:** Threat Intelligence.
- **Service:** `threat-intel-service`.
- **Module/File:** `services/threat-intel-service/` (`store/`, `providers/`, `enrich/`).
- **Database:** Postgres `threat_indicator`, `threat_actor`, `ti_source`; Redis reputation cache.
- **API:** `GET /api/v1/ti/indicators`, enrichment internal API.
- **Event:** produces `ti.updates`.
- **Frontend:** IOC explorer in threat-hunting panel — P4.
- **ML/AI:** N/A for core (reputation scoring is rule-based); optional actor-similarity via `memory-service` later.
- **Infrastructure:** external provider APIs (all optional, feature-flagged), egress proxy.
- **Security boundary:** TB-4 (untrusted provider responses — schema-validated, never fabricated).
- **Test:** provider-adapter tests with recorded fixtures, failure/timeout/malformed tests, freshness/expiry tests.
- **Verification method:** adapter unit tests (recorded fixtures), integration with local mock provider.
- **Phase:** P3. **Status:** ARCHITECTURE DEFINED.

### R10 — Lateral Movement Detection
- **Purpose:** credential reuse, privilege pivot, suspicious session tracking, internal traversal analysis.
- **Subsystem:** Detection / Stream / Graph.
- **Service:** `stream-processor` (`lateral-movement`) + `graph-service` + `detection-engine`.
- **Module/File:** `services/stream-processor/jobs/lateral-movement/`.
- **Database:** Neo4j (`:USED_CREDENTIAL_ON`, path queries); Postgres `detection`.
- **API:** lateral-movement findings in detection/graph APIs.
- **Event:** consumes `events.canonical` (auth+flow); produces `graph.commands` + candidate `detections`.
- **Frontend:** lateral-movement path visualization — P4.
- **ML/AI:** graph + temporal + identity signal fusion; rule/graph-pattern first, GNN subgraph classifier (R11) enhances later.
- **Infrastructure:** Flink keyed state per identity, Neo4j.
- **Security boundary:** internal; tenant-keyed.
- **Test:** synthetic lateral-movement scenario → expected path + detection; false-positive guard tests.
- **Verification method:** scenario fixtures + CTU-13 / LANL derived cases (evaluation, unclaimed).
- **Phase:** P4. **Status:** ARCHITECTURE DEFINED.

### R11 — Graph Neural Network Layer
- **Purpose:** GraphSAGE, GAT, threat-cluster discovery, predictive attacker modeling, node anomaly + suspicious-subgraph classification.
- **Subsystem:** ML / Graph.
- **Service:** `ml-training` (train) + `ml-inference` (serve) + `graph-service` (subgraph extraction).
- **Module/File:** `ml/models/{graphsage,gat}/`, `ml/features/graph/`, `services/ml-*`.
- **Database:** MLflow registry, S3 artifacts; Neo4j (subgraph source); Postgres (scored outputs via `detection-engine`).
- **API:** internal inference API (`node_score`, `subgraph_class`).
- **Event:** scores flow into `detections`.
- **Frontend:** GNN-flagged nodes/subgraphs highlighted in graph view — P5.
- **ML/AI:** PyTorch Geometric GraphSAGE/GAT; graph input = tenant subgraph with feature schema (versioned); **no metrics claimed** — `NOT VERIFIED — REQUIRES REAL DATA / TRAINING ENVIRONMENT` + GPU (external).
- **Infrastructure:** MLflow, S3, GPU node pool (external requirement).
- **Security boundary:** subgraph extraction tenant-scoped; artifacts from trusted registry only.
- **Test:** graph-batch construction tests, training-pipeline smoke test (tiny synthetic graph), inference contract tests, reproducibility.
- **Verification method:** benchmark harness on CTU-13 / UNSW-NB15 graph representations — not yet run.
- **Phase:** P5. **Status:** ARCHITECTURE DEFINED.

### R12 — Temporal Analysis Engine
- **Purpose:** threat reconstruction, historical replay, cross-session attack stitching, chronological reconstruction.
- **Subsystem:** Stream / Graph.
- **Service:** `stream-processor` (`temporal-stitcher`) + `graph-service` (time-on-edge queries) + Kafka replay.
- **Module/File:** `services/stream-processor/jobs/temporal-stitcher/`, `services/graph-service/query/temporal.py`.
- **Database:** Neo4j (relationship `observed_at`); Kafka (`events.canonical` replay); Postgres (reconstructed timelines).
- **API:** `GET /api/v1/timeline/{entity}` via `api-gateway` → `graph-service`.
- **Event:** consumes/produces `events.canonical` (enriched `correlation_id`), optional `identity.links`.
- **Frontend:** threat timeline, historical replay scrubber — P4.
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE (sequencing is deterministic on event-time).
- **Infrastructure:** Flink event-time + watermarks, Kafka retention for replay window.
- **Security boundary:** internal; replay into side-effecting consumers forbidden (dedicated replay groups).
- **Test:** event-time ordering tests, replay-idempotency tests, cross-session stitch fixtures.
- **Verification method:** integration replay test; deterministic reconstruction fixtures.
- **Phase:** P4. **Status:** ARCHITECTURE DEFINED.

### R13 — Attack Visualization Dashboard
- **Purpose:** live attack graph, cinematic attack replay, SOC interface, threat timelines, entity relationship explorer, risk heatmaps.
- **Subsystem:** Frontend / Realtime.
- **Service:** `frontend/web` + `api-gateway` + `notification-service`.
- **Module/File:** `frontend/web/app/(soc)/graph`, `.../timeline`, `.../heatmap`; `services/notification-service/`.
- **Database:** N/A directly (via api-gateway); Redis fan-out for realtime.
- **API:** `api-gateway` graph/detection/timeline endpoints + WebSocket.
- **Event:** consumes `graph.events`, `detections` via Redis fan-out.
- **Frontend:** Cytoscape.js graph, D3 timeline/heatmap, replay controls.
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **Infrastructure:** Next.js runtime, WebSocket, Redis.
- **Security boundary:** TB-2; tenant-locked subscriptions; CSP; no direct datastore access.
- **Test:** component tests, Playwright e2e (login → graph loads → live update), WS auth tests.
- **Verification method:** Playwright e2e against docker-compose stack.
- **Phase:** P4. **Status:** ARCHITECTURE DEFINED.

### R14 — Alert Explanation Engine
- **Purpose:** human-readable explanations, root-cause summaries, attack-path interpretation, analyst-focused reasoning — grounded in system evidence.
- **Subsystem:** AI Analyst.
- **Service:** `ai-analyst-service`.
- **Module/File:** `services/ai-analyst-service/explain/`.
- **Database:** Postgres `explanation`.
- **API:** `GET /api/v1/detections/{id}/explanation` via `api-gateway`.
- **Event:** consumes `detections`, `attack_chains` (may pre-generate).
- **Frontend:** explanation panel on alert detail — P6.
- **ML/AI:** LLM via provider adapter; **evidence-grounded** (explanation contract §7.2 — every claim traces to evidence); no fabricated reasoning; `LLM_UNAVAILABLE` handled with deterministic template fallback.
- **Infrastructure:** LLM providers (external), egress proxy.
- **Security boundary:** TB-4; retrieved content = data not instructions; prompt + response audited.
- **Test:** grounding tests (assert every summary claim has an evidence ref), injection tests, fallback tests, recorded-fixture LLM tests.
- **Verification method:** contract + grounding unit tests; manual review of sample explanations (labeled as review, not metric).
- **Phase:** P6. **Status:** ARCHITECTURE DEFINED.

### R15 — Predictive Threat Engine
- **Purpose:** forecast attack progression, threat-trajectory modeling, predict next attacker action, forecast lateral movement, early-compromise prediction.
- **Subsystem:** ML.
- **Service:** `ml-training` + `ml-inference` + `detection-engine` (consumes forecasts).
- **Module/File:** `ml/models/predictive/`, `services/detection-engine/predict/`.
- **Database:** MLflow, S3; Postgres (predictions with confidence + horizon).
- **API:** predictions in chain/entity detail via `api-gateway`.
- **Event:** forecasts attached to `attack_chains` updates.
- **Frontend:** predicted next-step overlay on attack graph/timeline — P6.
- **ML/AI:** sequence/temporal model (architecture TBD in P5 spike); outputs `{predicted_action, probability, horizon, confidence}`; **no accuracy claimed**; failure → no prediction (never a guessed one).
- **Infrastructure:** MLflow, S3, GPU (external).
- **Security boundary:** tenant-scoped inputs; predictions are advisory, never trigger auto-response.
- **Test:** pipeline smoke tests, calibration test scaffold, failure-behavior tests.
- **Verification method:** backtesting harness on CTU-13 attack sequences — not yet run.
- **Phase:** P6. **Status:** ARCHITECTURE DEFINED.

### R16 — Deception & Honeypot Module
- **Purpose:** decoy services, attacker-interaction tracking, adversary profiling; controlled isolation.
- **Subsystem:** Deception.
- **Service:** `deception-service` (network-isolated, TB-6).
- **Module/File:** `services/deception-service/` (`control/`, `capture/`, `profile/`).
- **Database:** Postgres isolated schema `decoy`, `decoy_interaction`, `adversary_profile`.
- **API:** admin API to deploy/manage decoys (role-gated); one-way telemetry export.
- **Event:** exports to `events.canonical` as `source.type = deception`.
- **Frontend:** decoy management + interaction feed — P9.
- **ML/AI:** adversary profiling (clustering) — optional, later.
- **Infrastructure:** isolated network segment; decoy runtimes (containers/VMs) — external for real deployment.
- **Security boundary:** **invariant: no route from deception segment into production data planes or credentials**; decoy data cannot auto-trigger response.
- **Test:** isolation tests (assert no reachability to prod services), export-path tests, injection-from-decoy handling.
- **Verification method:** network-policy tests in k8s (later); local isolation simulated.
- **Phase:** P9. **Status:** ARCHITECTURE DEFINED. **EXTERNALLY DEPENDENT** for real decoy infra.

### R17 — Attack Simulation Mode
- **Purpose:** APT/ransomware/insider/brute-force simulations, synthetic attack generation, interactive replay — isolated and safe.
- **Subsystem:** Simulation.
- **Service:** `simulation-service` (TB-7).
- **Module/File:** `services/simulation-service/` (`scenarios/`, `engine/`, `replay/`).
- **Database:** Postgres `simulation`, `simulation_run`, `scenario`.
- **API:** `POST /api/v1/simulations` (role-gated), run control, replay.
- **Event:** synthetic events labeled `metadata.simulation = true` / `source.type = simulation`.
- **Frontend:** simulation launcher + replay UI — P9.
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE (scenarios are scripted/deterministic).
- **Infrastructure:** isolated execution; no external network.
- **Security boundary:** **invariant: never generates real traffic/attacks; cannot emit `response.actions`; all output labeled `SIMULATION`; deterministic + reproducible**.
- **Test:** determinism tests (same seed → same events), label-propagation tests, "cannot emit response.action" test, isolation test.
- **Verification method:** unit + integration; determinism assertions.
- **Phase:** P9. **Status:** ARCHITECTURE DEFINED.

### R18 — Threat Hunting Panel
- **Purpose:** IOC exploration, graph pivoting, advanced graph querying, search users/devices/chains/indicators.
- **Subsystem:** Frontend / Graph / API.
- **Service:** `frontend/web` + `api-gateway` + `graph-service` (+ `ai-analyst-service` for NL, R32).
- **Module/File:** `frontend/web/app/(soc)/hunt`, `services/graph-service/query/`.
- **Database:** Neo4j (traversal), Postgres (entity attrs), full-text indexes.
- **API:** `POST /api/v1/hunt/query` (structured), `.../search`, NL endpoint (R32).
- **Event:** N/A (interactive).
- **Frontend:** hunt workspace, pivot UI, saved queries.
- **ML/AI:** NL hunting via R32 (constrained).
- **Infrastructure:** Neo4j full-text, Postgres.
- **Security boundary:** every hunt query authorized (`hunt:query` permission) + tenant-scoped + depth/row/time capped; hunt queries audited.
- **Test:** authorization tests, tenant-isolation tests (hunt cannot see other tenant), query-cap tests.
- **Verification method:** security + integration tests.
- **Phase:** P4. **Status:** ARCHITECTURE DEFINED.

### R19 — Knowledge Graph Layer
- **Purpose:** Neo4j integration, persistent attack memory, historical attacker profiling, relationship-aware traversal, attack-path analytics.
- **Subsystem:** Graph.
- **Service:** `graph-service` (+ `memory-service` for non-graph memory).
- **Module/File:** `services/graph-service/knowledge/` (promotion logic).
- **Database:** Neo4j knowledge partition (`graph = 'kg'` / separate DB on Enterprise).
- **API:** knowledge-graph queries via `api-gateway`.
- **Event:** consumes confirmed `attack_chains`, investigation-closed events → promotion.
- **Frontend:** historical attacker profile views — P6.
- **ML/AI:** feeds R37 memory-augmented reasoning.
- **Infrastructure:** Neo4j (Enterprise licensing question U-003/U-008 for prod scale).
- **Security boundary:** tenant-scoped; promotion is an explicit, audited event.
- **Test:** promotion-logic tests, operational-vs-knowledge separation tests, retention/prune tests.
- **Verification method:** integration tests against Neo4j; ADR-011 boundary assertions.
- **Phase:** P3 (operational), P6 (promotion/history). **Status:** ARCHITECTURE DEFINED.

### R20 — Stream Processing Architecture
- **Purpose:** Kafka pipelines, Flink orchestration, fault-tolerant streaming; distinct roles for Kafka / Redis / Flink; DLQ, consumer groups, partitioning, ordering, replay, backpressure.
- **Subsystem:** Platform / Stream.
- **Service:** `stream-processor` (Flink) + Kafka infra + Redis.
- **Module/File:** `services/stream-processor/`, `deploy/docker` (Redpanda), `packages/common-py/kafka/`.
- **Database:** Flink state + S3 checkpoints; Kafka topics.
- **API:** N/A.
- **Event:** the entire topic taxonomy (`event-model.md §3`); at-least-once; **exactly-once NOT claimed**.
- **Frontend:** N/A (ops dashboards in R23).
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **Infrastructure:** Kafka/Redpanda, Flink (JDK 11+ — **external, absent locally**), Redis, S3.
- **Security boundary:** TB-3; SASL_SSL + ACLs in prod; per-key tenant isolation in state.
- **Test:** DLQ tests, consumer-lag/backpressure tests, checkpoint-restore tests, ordering tests, replay tests.
- **Verification method:** integration tests with Redpanda; Flink job tests (mini-cluster) — **EXTERNALLY DEPENDENT** (needs JDK 11+/Flink).
- **Phase:** P2 (Kafka), P3–P4 (Flink jobs). **Status:** ARCHITECTURE DEFINED. Kafka-vs-Redis-vs-Flink roles: **RESOLVED** (ADR-008/009/010).

### R21 — Threat Memory System
- **Purpose:** behavioral pattern persistence, campaign-evolution tracking, cross-incident intelligence retention; storage/retrieval/retention/tenant isolation.
- **Subsystem:** Memory.
- **Service:** `memory-service`.
- **Module/File:** `services/memory-service/` (`patterns/`, `campaigns/`, `retrieval/`).
- **Database:** Postgres + pgvector `threat_memory`, `campaign`.
- **API:** internal retrieval API; campaign views via `api-gateway`.
- **Event:** consumes `detections`, `attack_chains`; produces `campaign.updates`.
- **Frontend:** campaign timeline, behavioral-pattern browser — P6.
- **ML/AI:** embedding generation for patterns/fingerprints; similarity search (pgvector).
- **Infrastructure:** Postgres + pgvector.
- **Security boundary:** strict tenant scoping; cross-tenant similarity **disabled by default** (only via federated mesh R34 with privacy controls).
- **Test:** retention tests, tenant-isolation tests, retrieval-relevance scaffold, degradation (pgvector down → exact fallback).
- **Verification method:** integration tests against Postgres+pgvector.
- **Phase:** P6. **Status:** ARCHITECTURE DEFINED.

### R22 — Threat Report Generator
- **Purpose:** executive summaries, automated SOC reports, compliance-ready PDF reports.
- **Subsystem:** Reporting.
- **Service:** `reporting-service`.
- **Module/File:** `services/reporting-service/` (`templates/`, `render/`).
- **Database:** Postgres `report`, `report_template`; S3 (PDF artifacts).
- **API:** `POST /api/v1/reports`, `GET /api/v1/reports/{id}` (pre-signed download).
- **Event:** produces `report.generated`.
- **Frontend:** report builder + library — P8.
- **ML/AI:** optional LLM-generated narrative sections via `ai-analyst-service` (grounded, labeled); never fabricated data.
- **Infrastructure:** PDF renderer, S3.
- **Security boundary:** role-gated (compliance reports `lead`/`tenant_admin`); tenant-scoped content; pre-signed URLs, no public buckets.
- **Test:** template-render tests, `PARTIAL` handling (missing content dep), authorization tests.
- **Verification method:** integration tests producing a PDF to MinIO.
- **Phase:** P8. **Status:** ARCHITECTURE DEFINED.

### R23 — Observability & Monitoring
- **Purpose:** infra observability, model monitoring, threat-trend dashboards, detection-latency metrics, false-positive tracking, graph-growth analytics.
- **Subsystem:** Platform / Observability.
- **Service:** all services (emit) + `deploy/prometheus` + `deploy/grafana`.
- **Module/File:** `packages/common-py/observability/`, `deploy/prometheus/`, `deploy/grafana/`.
- **Database:** Prometheus TSDB; Loki (logs); Tempo/Jaeger (traces).
- **API:** `/metrics` per service; `/healthz`, `/readyz`, `/health/deps`.
- **Event:** trace context in the event envelope (`trace_id`).
- **Frontend:** Grafana (ops); in-app threat-trend dashboards — P8.
- **ML/AI:** model-monitoring metrics (latency, `DEGRADED`, drift counters) — values only when real.
- **Infrastructure:** OTel collector, Prometheus, Grafana, Loki, Tempo.
- **Security boundary:** metrics endpoints internal only; log redaction mandatory.
- **Test:** metric-emission unit tests, health/readiness behavior tests, redaction tests.
- **Verification method:** assert metrics present via test scrape; **no fabricated measurements**.
- **Phase:** P1 (health/logging/request IDs), P8 (dashboards). **Status:** PARTIALLY DEFINED — P1 foundation pending implementation.

### R24 — Benchmark & Evaluation System
- **Purpose:** CICIDS2017, UNSW-NB15, NSL-KDD, CTU-13, LANL, EMBER; ROC-AUC benchmarking; baseline IDS comparison; reproducibility; experiment tracking.
- **Subsystem:** ML.
- **Service:** `ml-training` (benchmark harness).
- **Module/File:** `ml/datasets/<name>/` (adapters + `MANIFEST.md`), `services/ml-training/benchmark/`.
- **Database:** MLflow experiments; Postgres `benchmark_experiment`; S3 (reports).
- **API:** N/A (batch); results surfaced in docs + Grafana after real runs.
- **Event:** N/A.
- **Frontend:** benchmark results page — P8 (populated only from real runs).
- **ML/AI:** the models under evaluation (R5, R11, R15).
- **Infrastructure:** datasets at `SM_DATASET_ROOT` (staged: NSL-KDD, UNSW-NB15, CTU-13, EMBER, LANL; **CICIDS2017 to be added**), MLflow, GPU (external).
- **Security boundary:** research datasets, no tenant data; dataset licenses recorded per `MANIFEST.md`.
- **Test:** dataset-adapter tests (schema, splits, checksums), harness smoke test, reproducibility test.
- **Verification method:** run harness → metrics to MLflow. **NOT VERIFIED — REQUIRES REAL DATA / TRAINING ENVIRONMENT.** No metric exists yet.
- **Phase:** P5. **Status:** ARCHITECTURE DEFINED. Datasets partly staged (see `C:\Sentinel_Mesh`).

### R25 — Beautiful Enterprise UI
- **Purpose:** professional SOC dashboard, advanced graph visualization, security analytics dashboards; accessibility + security + performance preserved.
- **Subsystem:** Frontend.
- **Service:** `frontend/web`.
- **Module/File:** `frontend/web/` (design system, layouts, dashboards).
- **Database:** N/A (via api-gateway).
- **API:** `api-gateway` `/api/v1/*`.
- **Event:** WebSocket updates.
- **Frontend:** design system, SOC shell, dashboards, graph explorer, heatmaps.
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **Infrastructure:** Next.js.
- **Security boundary:** TB-2; CSP, sanitized rendering of analyst/LLM text, a11y (WCAG AA target).
- **Test:** component tests, a11y checks (axe), visual regression (optional), performance budget checks.
- **Verification method:** CI a11y + component tests; Lighthouse budget (informational).
- **Phase:** P4 (core), P8 (polish). **Status:** ARCHITECTURE DEFINED.

### R26 — Demo Scenario Engine
- **Purpose:** investor-ready demos, interactive breach simulations, live hosted demo environments — synthetic, deterministic, reproducible, clearly labeled.
- **Subsystem:** Simulation / Frontend.
- **Service:** `simulation-service` (scenario engine) + `frontend/web` (demo mode).
- **Module/File:** `services/simulation-service/scenarios/demo/`, `frontend/web/app/demo/`.
- **Database:** Postgres `scenario` (demo-flagged).
- **API:** demo control endpoints (role-gated or demo-tenant-scoped).
- **Event:** synthetic, labeled `metadata.simulation = true`.
- **Frontend:** guided demo walkthrough UI.
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **Infrastructure:** a dedicated demo tenant + isolated data.
- **Security boundary:** **invariant: demo activity is never presented as a real incident; demo data isolated to a demo tenant**.
- **Test:** determinism tests, label tests, "no real-incident classification" test.
- **Verification method:** e2e demo run assertions.
- **Phase:** P9. **Status:** ARCHITECTURE DEFINED.

### R27 — Documentation Ecosystem
- **Purpose:** API docs, README optimization, infra flowcharts, architecture diagrams, demo GIFs, benchmarks, ATT&CK mapping docs, setup instructions — accurate to implementation status.
- **Subsystem:** Documentation.
- **Service:** N/A (repo artifacts).
- **Module/File:** `docs/`, `README.md`, generated OpenAPI, `docs/architecture/*`, per-service `README.md` (added as services are built).
- **Database:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **API:** OpenAPI served by `api-gateway` at `/api/v1/openapi.json` + docs UI (non-prod).
- **Event:** N/A.
- **Frontend:** N/A (docs site optional later).
- **ML/AI:** N/A.
- **Infrastructure:** static docs; diagram sources in-repo (Mermaid).
- **Security boundary:** docs must not contain secrets or fabricated results (Constitution §3, §20).
- **Test:** doc-lint (links, TOC), "no fabricated metric" grep check in CI, OpenAPI schema validation.
- **Verification method:** CI doc checks; this file + `IMPLEMENTATION_STATE.md` kept current each phase.
- **Phase:** all phases (continuous). **Status:** IN PROGRESS (Phase 0 docs created).

### R28 — Technical Content & Branding Layer
- **Purpose:** technical blog ecosystem, research-style writeups, demo video ecosystem (e.g. "Why Graph AI…", "How GNNs Detect Lateral Movement").
- **Subsystem:** Content (non-runtime).
- **Service:** N/A — **NOT a core runtime security dependency** (per architecture note).
- **Module/File:** `docs/content/` (later) or a separate marketing repo.
- **Database:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **API:** N/A.
- **Event:** N/A.
- **Frontend:** marketing site (out of scope for the platform repo).
- **ML/AI:** N/A.
- **Infrastructure:** N/A for the platform.
- **Security boundary:** content must not disclose customer data or fabricated benchmarks.
- **Test:** N/A for runtime; editorial review.
- **Verification method:** editorial; not a code-verified requirement.
- **Phase:** P8+ (after real results exist to write about). **Status:** ACKNOWLEDGED — NON-RUNTIME.

### R29 — Autonomous AI Security Analyst Layer
- **Purpose:** LLM-powered SOC analyst, automatic incident triage, AI remediation suggestions — with adapter, grounding, tool permissions, authorization, injection defense, auditability, human-approval boundaries.
- **Subsystem:** AI Analyst.
- **Service:** `ai-analyst-service` (+ `agent-orchestrator` for actions).
- **Module/File:** `services/ai-analyst-service/` (`llm/`, `context/`, `triage/`).
- **Database:** Postgres `analyst_message`, `explanation`.
- **API:** `POST /api/v1/analyst/triage/{detection_id}`, chat endpoint.
- **Event:** consumes `detections`; may create `agent.tasks` (suggestions only by default).
- **Frontend:** analyst chat + triage panel — P6.
- **ML/AI:** LLM provider adapter (ADR-014); context = system evidence with provenance; tool allow-list per task; **suggestions never auto-execute** (ADR-022).
- **Infrastructure:** LLM providers (external), egress proxy.
- **Security boundary:** TB-4; prompt-injection defense; every prompt/response/tool-call audited; agent runs under constrained principal.
- **Test:** grounding tests, injection tests, tool-authorization tests, "suggestion ≠ action" test, audit-completeness test.
- **Verification method:** security + contract tests with recorded LLM fixtures.
- **Phase:** P6 (analyst), P7 (agent actions). **Status:** ARCHITECTURE DEFINED.

### R30 — Multi-Agent Cyber Defense System
- **Purpose:** detection agent, threat-intelligence agent, response-orchestration agent — with boundaries, tool access, comms protocol, state, authorization, audit, failure isolation.
- **Subsystem:** Agents.
- **Service:** `agent-orchestrator`.
- **Module/File:** `services/agent-orchestrator/agents/{detection,threat_intel,response}/`, `.../protocol/`.
- **Database:** Postgres `agent_task`.
- **API:** internal; task status via `api-gateway`.
- **Event:** `agent.tasks` topic is the comms bus; state in Postgres.
- **Frontend:** agent activity view — P7.
- **ML/AI:** agents use `ai-analyst-service` LLM + deterministic tools.
- **Infrastructure:** Kafka, Postgres.
- **Security boundary:** each agent = constrained service principal + task-scoped tool allow-list; **no autonomous privilege escalation**; failure of one agent isolated (task-level).
- **Test:** boundary tests (agent cannot exceed allow-list), protocol tests, failure-isolation tests, audit tests.
- **Verification method:** security + integration tests.
- **Phase:** P7. **Status:** ARCHITECTURE DEFINED.

### R31 — Autonomous Response Engine
- **Purpose:** endpoint isolation, firewall-rule generation, automated SOAR workflows — with authorization, approval, policy, blast radius, rollback, auditability, failure handling.
- **Subsystem:** Response.
- **Service:** `agent-orchestrator` (response engine) + provider adapters.
- **Module/File:** `services/agent-orchestrator/response/`, `.../adapters/{edr,firewall,soar}/`.
- **Database:** Postgres `response_action`, `response_policy`, `approval`.
- **API:** `POST /api/v1/response/actions` (role-gated), approval endpoints.
- **Event:** produces `response.actions`.
- **Frontend:** response console + approval queue — P7.
- **ML/AI:** suggestions from R29/R30; execution is policy-gated deterministic.
- **Infrastructure:** external EDR/firewall/SOAR — **adapters, default OFF**.
- **Security boundary:** TB-5; `suggest_only` default; `auto` only in production + signed policy + allow-listed action type + rollback plan; every action authorized + policy-checked + blast-radius-computed + audited.
- **Test:** policy-enforcement tests, approval-gate tests, "no auto outside prod" config test, rollback tests, adapter-failure tests.
- **Verification method:** security + integration tests with mock adapters. **Real endpoint isolation / firewall change: NOT VERIFIED — REQUIRES ACTUAL INTEGRATION + VERIFIED ENVIRONMENT.**
- **Phase:** P7. **Status:** ARCHITECTURE DEFINED.

### R32 — Natural Language Threat Hunting
- **Purpose:** AI-to-Cypher translation, conversational SOC interface, context-aware exploration — never unrestricted LLM DB execution.
- **Subsystem:** AI Analyst / Graph.
- **Service:** `ai-analyst-service` (NL→`QueryPlan`) + `graph-service` (deterministic compile+execute).
- **Module/File:** `services/ai-analyst-service/nlq/`, `services/graph-service/query/plan_compiler.py`.
- **Database:** Neo4j (read-only role); Postgres `hunt_query` (history).
- **API:** `POST /api/v1/hunt/nl` (returns results + grounded explanation).
- **Event:** N/A.
- **Frontend:** conversational hunt UI — P6.
- **ML/AI:** LLM produces closed-schema `QueryPlan` (ADR-015); **LLM never emits executed Cypher**; deterministic builder → parameterized Cypher → read-only role → capped.
- **Infrastructure:** LLM providers, Neo4j read replica/role.
- **Security boundary:** authorization on the `QueryPlan` (tenant, allowed intents, depth/row caps); unsupported → `unsupported_query`; every NL query audited.
- **Test:** "no raw Cypher execution" test, `QueryPlan` validation tests, authorization tests, injection tests, tenant-isolation tests.
- **Verification method:** security + contract tests; adversarial prompt fixtures.
- **Phase:** P6. **Status:** ARCHITECTURE DEFINED. Constraint **RESOLVED** (ADR-015).

### R33 — Attack Storytelling Engine
- **Purpose:** cinematic attack narratives, breach replay, executive walkthroughs — grounded in actual evidence; simulations clearly labeled.
- **Subsystem:** AI Analyst / Frontend.
- **Service:** `ai-analyst-service` (`narrative/`) + `frontend/web` (replay).
- **Module/File:** `services/ai-analyst-service/narrative/`, `frontend/web/app/(soc)/story/`.
- **Database:** Postgres `narrative`.
- **API:** `GET /api/v1/incidents/{id}/narrative`.
- **Event:** consumes `attack_chains`, incident events.
- **Frontend:** cinematic replay component (uses graph + timeline).
- **ML/AI:** LLM narrative generation, **grounded** (every beat references evidence); simulation-sourced narratives labeled `SIMULATION`.
- **Infrastructure:** LLM providers.
- **Security boundary:** TB-4; no fabricated events in narratives; grounding enforced like R14.
- **Test:** grounding tests, label tests (simulation vs real), fallback tests.
- **Verification method:** contract + grounding tests; sample review.
- **Phase:** P6 (narrative), P9 (cinematic polish). **Status:** ARCHITECTURE DEFINED.

### R34 — Federated Threat Intelligence Mesh
- **Purpose:** federated learning, distributed anomaly learning, collective defense — with participant trust, privacy, model/update exchange, aggregation, poisoning defenses, tenant isolation, provenance.
- **Subsystem:** Federation.
- **Service:** `federation-service` — **DEFERRED (ADR-023)**.
- **Module/File:** `services/federation-service/` (contract stub only until P10).
- **Database:** (future) Postgres `federation_participant`, `model_update`, `aggregation_round`.
- **API:** (future) participant enrollment, update submission, aggregate distribution.
- **Event:** (future) `federation.rounds`.
- **Frontend:** (future) federation status.
- **ML/AI:** federated averaging / secure aggregation; differential-privacy clipping on updates; aggregation-side poisoning detection.
- **Infrastructure:** (future) participant coordination, secure channels.
- **Security boundary:** **no raw data exchange**; signed updates; per-participant trust; privacy budget; strict isolation from single-tenant memory (R21).
- **Test:** (future) poisoning-defense tests, privacy tests, aggregation-correctness tests.
- **Verification method:** **NOT VERIFIED — DEFERRED.** No federated-learning performance will be claimed without actual evaluation.
- **Phase:** P10. **Status:** ARCHITECTURE DEFINED — DEFERRED.

### R35 — Security Digital Twin
- **Purpose:** attack blast-radius prediction, defensive stress testing, predictive resilience analysis — with environment representation, asset relationships, simulation model, scenario execution, isolation, safety.
- **Subsystem:** Simulation.
- **Service:** `simulation-service` (`twin/`).
- **Module/File:** `services/simulation-service/twin/`.
- **Database:** Postgres `digital_twin_model` (environment + asset graph snapshot).
- **API:** `POST /api/v1/twin/scenarios`, results endpoints.
- **Event:** N/A (isolated).
- **Frontend:** twin scenario builder + blast-radius visualization — P9.
- **ML/AI:** uses R15 predictive models + graph reachability; outputs probabilistic, uncertainty stated.
- **Infrastructure:** isolated; twin is a snapshot/model, not live infra.
- **Security boundary:** TB-7; twin runs cannot affect production detection or emit response actions; predictions labeled probabilistic.
- **Test:** isolation tests, reproducibility, "no production impact" tests.
- **Verification method:** unit + integration; **predictions are not accuracy-claimed**.
- **Phase:** P9. **Status:** ARCHITECTURE DEFINED.

### R36 — AI-Powered Root Cause Engine
- **Purpose:** entry-point analysis, misconfiguration discovery, breach causality mapping — evidence-based, no false certainty.
- **Subsystem:** AI Analyst.
- **Service:** `ai-analyst-service` (`rca/`).
- **Module/File:** `services/ai-analyst-service/rca/`.
- **Database:** Postgres `root_cause_analysis`.
- **API:** `GET /api/v1/incidents/{id}/root-cause`.
- **Event:** consumes incident + `attack_chains` + graph context.
- **Frontend:** root-cause panel with evidence chain — P6.
- **ML/AI:** LLM reasoning over graph paths + timeline; **causality is evidence-linked and probabilistic** — "likely entry point" with confidence, never asserted certainty when evidence is probabilistic.
- **Infrastructure:** LLM providers, `graph-service`.
- **Security boundary:** TB-4; grounding enforced; audited.
- **Test:** grounding tests, confidence-calibration scaffold, "no unwarranted certainty" lint on output schema (requires `confidence` + `evidence`).
- **Verification method:** contract + grounding tests; sample review.
- **Phase:** P6. **Status:** ARCHITECTURE DEFINED.

### R37 — Memory-Augmented Threat Reasoning
- **Purpose:** adversary fingerprinting, campaign-similarity analysis, persistent threat reasoning — relationship with Threat Memory (R21), Knowledge Graph (R19), AI Analyst (R29), Predictive (R15).
- **Subsystem:** Memory / AI Analyst.
- **Service:** `memory-service` (retrieval) + `ai-analyst-service`/`agent-orchestrator` (consumers).
- **Module/File:** `services/memory-service/fingerprint/`, `.../similarity/`.
- **Database:** Postgres + pgvector `adversary_fingerprint`, `campaign_similarity`.
- **API:** internal retrieval API; "similar past campaigns" in analyst UI.
- **Event:** consumes `campaign.updates`, `attack_chains`.
- **Frontend:** "seen before" panel linking current activity to historical campaigns — P6.
- **ML/AI:** embedding + similarity; **introduces no new store** (ADR-011) — composes R21 + R19 + R15.
- **Infrastructure:** pgvector; Neo4j knowledge graph.
- **Security boundary:** tenant-scoped; cross-tenant similarity only via R34 with privacy controls.
- **Test:** "no duplicate memory store" architecture test, retrieval tests, tenant-isolation tests.
- **Verification method:** integration tests; ADR-011 boundary assertions.
- **Phase:** P6. **Status:** ARCHITECTURE DEFINED. Relationship to R19/R21/R15/R29: **RESOLVED** (ADR-011).

### R38 — Enterprise Deployment & Scalability Layer
- **Purpose:** Kubernetes deployment, RBAC, SSO, Prometheus + Grafana — topology, namespaces, services, ingress, secrets, probes, resources, autoscaling, network policies, storage, backup/recovery, rollout.
- **Subsystem:** Platform / SRE.
- **Service:** all (packaged) + `deploy/helm`, `deploy/k8s`.
- **Module/File:** `deploy/`, per-service `Dockerfile`, `docs/architecture/deployment.md`.
- **Database:** managed Postgres/Neo4j/Kafka in prod (reference).
- **API:** N/A (platform).
- **Event:** N/A.
- **Frontend:** served as a container behind ingress.
- **ML/AI:** GPU node pool for `ml-*` (external).
- **Infrastructure:** Kubernetes, Helm, ingress, cert-manager, External Secrets Operator, Prometheus/Grafana/Loki/Tempo, Velero.
- **Security boundary:** TB-3; default-deny NetworkPolicies; per-service ServiceAccount + least-privilege RBAC; secrets via KMS/Vault; SSO via OIDC (ADR-016).
- **Test:** Helm lint/template tests, policy tests (OPA/conftest), kind-based smoke deploy (CI, later).
- **Verification method:** **NOT VERIFIED — REQUIRES EXTERNAL INFRASTRUCTURE (Docker/Kubernetes absent locally, ADR-001).** No cluster rollout is or will be claimed without an actual verified deployment.
- **Phase:** P1 provides local `docker-compose` + auth/RBAC/SSO foundation; full P38 hardening runs across late phases. **Status:** ARCHITECTURE DEFINED; auth/RBAC/SSO foundation pending P1 implementation.

---

## Coverage check

| Bucket | Requirements | Count |
|---|---|---|
| Foundation | 18(parts), 20, 23, 38, + P1 platform | — |
| Core runtime | 1, 2, 3, 4, 5, 6, 8, 9, 10, 19 | 10 |
| Advanced intelligence | 7, 11, 12, 14, 15, 16, 17, 21, 29, 32, 36, 37 | 12 |
| Enterprise | 22, 24, 30, 31, 34, 35, 38 | 7 |
| Presentation / content | 13, 18, 25, 26, 27, 28, 33 | 7 |

**All 38 requirements are present and mapped. None removed, none merged away,
none simplified out.** Requirements whose implementation is deferred (R34) or
non-runtime (R28) are explicitly marked, not dropped.
