# Requirements Traceability — SentinelMesh 38-Point Architecture

Every requirement 1–38 appears. Each maps:
Requirement → Purpose → Subsystem → Service → Module/File → Database → API →
Event → Frontend → ML/AI → Infrastructure → Security boundary → Test →
Verification method → Phase → Status.

`N/A — NOT REQUIRED BY ARCHITECTURE` is stated explicitly where a field does not
apply. No field is silently omitted.

**Global status note.** As of Phase 1 Unit 4 (2026-09-08) the only implemented
runtime is the Phase-1 foundation: the contract package, the shared platform and
infrastructure-client library, the control-plane schema and migrations, and the
`api-gateway` service. Every other requirement's Status is
`ARCHITECTURE DEFINED` unless a narrower state is given.

Nothing has yet run against real infrastructure: no Postgres, Redis, Neo4j,
Kafka, OIDC provider, collector, GPU or cluster has been touched. Every
verification recorded so far is a unit, contract or offline check — see
`IMPLEMENTATION_STATE.md` for the exact commands and results. No performance,
latency, accuracy, benchmark or deployment claim exists anywhere.

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
- **API:** `POST /api/v1/ingest/{source_type}` + `POST /api/v1/ingest/batch` (per-sensor auth); size/rate limited (fail-closed).
- **Event:** produces `telemetry.raw` (payloads `telemetry.network_flow|auth_event|dns_query|process_exec|file_access` v1).
- **Frontend:** sensor-management screens (list/register/rotate) — P8.
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **Infrastructure:** Kafka (Redpanda local), Redis.
- **Security boundary:** TB-1 (untrusted sensors); `tenant_id` bound to sensor identity, never trusted from body.
- **Test:** contract tests on envelope; security tests (bad credential, wrong-tenant payload, oversize, rate limit fail-closed); integration test sensor→topic.
- **Verification method:** integration test against Redpanda in docker-compose.
- **Phase:** P2. **Status:** IMPLEMENTED (Phase 2, Units 1–3), **INTEGRATION VERIFIED (CI)** — GitHub Actions run `34333269219` (`ubuntu-latest`): `integration` job green against service-container PostgreSQL 16 + Redis 7 + a runner-hosted Redpanda (`test_sensor_auth_pg.py`, `test_ingestion_bus_pg.py`); `image` job builds `ingestion-gateway` into `Dockerfile.app` and asserts the prod fail-fast guards. Also verified locally on the full compose stack + a live end-to-end (real sensor POST → `events.canonical`).
  - `sensor` registry table + `Sensor` contract + `SensorAuth` (`sm_common.security.sensor_auth`): INTEGRATION VERIFIED against real PostgreSQL — `tests/integration/test_sensor_auth_pg.py` (7 tests).
  - Telemetry payload contracts (`sm_contracts.telemetry`): IMPLEMENTED + unit-tested (`test_telemetry.py`, 13).
  - `ingestion-gateway` service (envelope built server-side, dedup, fail-closed limiter, batch): unit-tested against the real app with in-memory infra (`services/ingestion-gateway/tests`, ~40).
  - Bus: `sm_common.bus.EventBusProducer` (aiokafka, idempotent, `acks=all`) + `KafkaRawEventSink` / `KafkaDeadLetterSink`. **INTEGRATION VERIFIED** against real Redpanda — `tests/integration/test_ingestion_bus_pg.py`: an accepted sensor POST round-trips through `telemetry.raw` with the server-built envelope; a malformed body lands on `telemetry.raw.dlq` with `reason` / `sensor_id` headers. A produce failure fails the request with 503.

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
- **Phase:** P2. **Status:** IMPLEMENTED (Phase 2, Unit 4), **INTEGRATION VERIFIED (CI)** — run `34333269219`: the `integration` job's `test_normalization_bus.py` runs the full `telemetry.raw` → `events.canonical` loop and the poison → DLQ path against real Redpanda; also verified locally on the compose stack (live `normalization-engine` container). **Enrichment providers (Geo-IP, hostname, `identity_link` stitching, TI) are still NOT implemented** — protocol only.
  - `services/normalization-engine` — a stream processor consuming `telemetry.raw`, producing `events.canonical` (`event.canonical` v1). Deterministic per-source mapping (`normalize/mappers.py`) → `CanonicalEventPayload` with `actor`/`target`/`entities` and `raw_event_id`/`raw_event_type` lineage; `occurred_at`, `correlation_id`, `source` carried from the raw event.
  - `enrich/` is a stubbed `Enricher` protocol + runner — **Geo-IP, hostname resolution, identity stitching (`identity_link`), threat-intel tagging are NOT implemented** (no provider yet, so `enrichment = {}`); each is a later unit/phase. The `asset` / `identity_link` reads and the Redis geoip/TI cache are likewise not built.
  - Delivery: `sm_common.bus.EventBusConsumer`, manual commit after the side effect; poison → `telemetry.raw.dlq` wrapped per event-model.md §5; produce failure → retry then uncommitted redelivery.
  - **INTEGRATION VERIFIED** against real Redpanda — `tests/integration/test_normalization_bus.py`: a `telemetry.raw` record becomes an `events.canonical` envelope with lineage; a poison record is dead-lettered and the next good record still processes. Unit: `test_normalize.py` (6 golden mappings), `test_engine.py` (7).

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
- **Phase:** P3/P4. **Status:** PARTIAL — producer + writer + read/query API IMPLEMENTED and INTEGRATION VERIFIED (Phase 4 closed); GDS pathfinding/centrality pending (graph-ML phase).
  - **Producer** (Phase 3): `stream-processor`'s `graph-update-emitter` maps every `events.canonical` event to `MERGE` commands on `graph.commands`; deterministic `command_id`; INTEGRATION VERIFIED (`test_stream_processor_bus.py`).
  - **Writer** (Phase 4 Unit 2): `services/graph-service` consumes `graph.commands` (group `graph-writer`) and applies each as a **parameterized** MERGE (label / relationship type allowlist-validated against `sm_contracts.GRAPH_NODE_LABELS` / `GRAPH_REL_TYPES` — non-allowlisted → DLQ), idempotent by `command_id` (`_GraphCommand` ledger), out-of-order safe (`_watermark`), tenant invariants by construction (synthetic per-tenant `uid`; no cross-tenant edge), missing endpoint nodes created; emits `graph.events` (`GraphEventPayload`). INTEGRATION VERIFIED against a real Neo4j 5 Community container (`tests/integration/test_graph_service_neo4j.py` — node/edge creation, duplicate, out-of-order, duplicate-relationship suppression, tenant isolation).
  - **Read / query API** (Phase 4 Unit 3): `graph-service` `GET /api/v1/graph/{entity,neighbors,paths}` + `GraphRepository`. Parameterized only (label allowlisted, depth an int clamped to `SM_NEO4J_TRAVERSAL_MAX_DEPTH`); tenant scope is the verified internal-JWT `tenant_id`, never a request field; row-capped, `_`/`uid` props stripped. INTEGRATION VERIFIED (`test_graph_service_neo4j.py` — bounded neighbourhood, `shortestPath`, cross-tenant reads return nothing). **GDS** pathfinding/centrality — later.

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
- **Phase:** P3–P4. **Status:** PARTIAL. `events.canonical → graph.commands → graph-service → Neo4j` is live and idempotent (see R3). Per-partition ordering holds; out-of-order commands are resolved last-write-wins on `observed_at` (`_watermark`), verified in `test_graph_service_neo4j.py`. A Neo4j outage during apply surfaces as `TransientError` and the record is retried (not dropped). Kill/restore-from-checkpoint recovery is a stateful-engine concern (deferred, ADR-010).

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
- **Phase:** P5. **Status:** PARTIAL — pipeline IMPLEMENTED and INTEGRATION VERIFIED; trained models + benchmark pending.
  - `packages/ml-py` (`sm_ml`): versioned `FeatureSchema` per `CanonicalKind` + deterministic numpy-free extractors; `Preprocessor`; the `AnomalyModel` protocol; `StatisticalModel` (MAD z-score, stdlib-only — the always-on adaptive-threshold detector); `IsolationForestModel` (sklearn, artifact-loaded); `AutoencoderModel` architecture spec + `ModelNotTrained`; `ModelRegistry`. `ml/models/*/CONTRACT.md` per §6, `METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`.
  - `services/ml-inference` (ADR-013): typed `POST /infer/{model}`; a missing / unloadable model → HTTP 503 `MODEL_UNAVAILABLE`; per-model latency + error + load metrics.
  - `services/detection-engine`: `events.canonical` → features → per-`(tenant, kind)` rolling-window `StatisticalModel` (adaptive thresholds) → `anomaly` row; optional `ml-inference` contribution, any failure → `scoring_status = DEGRADED` + statistical only (verified). INTEGRATION VERIFIED against real PostgreSQL (`test_detection_pipeline_pg.py` — burst → `detection` + `security_alert` with grounded evidence, dedup on reprocess, tenant isolation).
  - **Trained Isolation Forest / autoencoder artifacts, and any accuracy / F1 / ROC-AUC number: `NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`** (ADR-024). No such number is produced or stored anywhere.

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
- **Phase:** P7. **Status:** IMPLEMENTED (CI-verified). `sm_contracts.chains` — `AttackStage` (14 ATT&CK-tactic kill-chain stages, in order, + `unknown` as a first-class value), `STAGE_ORDER`, `TACTIC_STAGE` (stable ATT&CK tactic ids) / `TECHNIQUE_STAGE` (**only** the techniques SentinelMesh's own rules emit — a small auditable map, not an ATT&CK-coverage claim), `stage_for_tactic` / `stage_for_technique` (unknown → `AttackStage.unknown`, never guessed); `ChainStatus` (forming/active/dormant — a chain is **never** auto-`confirmed`); `AttackChainModel` / `ChainStageModel` / `AttackChainPayload` on `attack_chains`; `chain_dedup_key` / `chain_window_start` (fixed tumbling window) / `chain_id_for`. `CONFIDENCE_CEILING = 0.95` — the platform never claims certainty. Alembic `0005` + `sm_common.db.chain_models` (`attack_chain` / `attack_chain_stage`). `services/correlation-engine` (port 8009, group `correlation`): consumes `detections`; `staging.py` places each detection on the furthest non-`unknown` kill-chain stage its techniques imply (`rule.ti.*` → TI-corroborated); `ChainRepository.correlate` upserts the deterministic-id chain + `attack_chain_stage` rows (detection ids as a set → idempotent redelivery; `min`/`max` timestamps → out-of-order safe; `ti_corroborated` monotonic; a stage transition backwards in kill-chain order over time is counted and discounts `confidence`, adds an `out_of_order_observed` note); recomputes `progression` / probabilistic `confidence` (≤ 0.95) / `ChainStatus`; emits `AttackChainPayload` on `attack_chains` and `graph.commands` (`:AttackChain` + `INVOLVES` + `MAPPED_TO` → `:AttackTechnique`). Read API `GET /api/v1/chains[/{chain_id}]` (internal-JWT, tenant from token). `mitre-service` also consumes `attack_chains` → `technique_mapping` (`subject_type = attack_chain`). `test_staging.py` / `test_scoring.py` / `test_engine.py` / `test_graph.py`; `tests/integration/test_chain_correlation_pg.py` (ordering, duplicate idempotency, out-of-order flagging, incomplete `forming` chain, dormancy, window separation, tenant isolation, TI monotonicity, degraded member) + `test_chain_pipeline_e2e_pg.py` (real PostgreSQL + real Neo4j — auth burst → detection → chain + `threat_score` + `:AttackChain` node with `INVOLVES` → `:Identity` and `MAPPED_TO` → `:AttackTechnique`). ML sequence inference (GraphSAGE/GAT etc.) remains future work (Phase 8), as traced.

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
- **Phase:** P6. **Status:** IMPLEMENTED (CI-verified). `sm_contracts.mitre` (`AttackTactic` / `AttackTechnique` / `AttackMatrixVersion` / `TechniqueMapping` / `TechniqueMatch`, `TECHNIQUE_ID_RE`, `parent_technique_id`). `services/mitre-service` (port 8008): `stix.py` parses a STIX 2.1 bundle → tactics/techniques/subtechniques + `AttackMatrixVersion` (`stix_bundle_sha256`, real counts); `CatalogRepository.import_catalog` replaces a version in one transaction; `MappingEngine` validates a subject's candidate `technique_ids` against the imported catalog — unknown or deprecated → `unmapped`, **never guessed**; consumes `detections` **and** `attack_chains` (group `mitre-mapping`, dispatch on `event_type`; a chain's subject is `attack_chain`, Phase 7) → `technique_mapping` upserts on `uq_technique_mapping_subject_technique_source`; `GET /api/v1/mitre/{techniques,heatmap}` + `POST /map` (internal-JWT, tenant from token); `/readyz` flags an empty catalog. `scripts/import_attack_stix.py` CLI. **No ATT&CK data ships** (ADR-024); `tests/fixtures/attack_mini_bundle.json` is a labelled fixture (2 tactics, 3 techniques, 1 sub-technique) and drives the tests. Coverage is exactly what is imported — no current-ATT&CK claim anywhere. `test_stix.py` / `test_mapping.py` / `test_engine.py` / `test_api.py`; `tests/integration/test_mitre_catalog_pg.py` (import records the matrix version, deprecated hidden, reimport replaces in place, map+persist+heatmap+tenant isolation).

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
- **Phase:** P5 → P7. **Status:** IMPLEMENTED (deterministic, two layers). **Per-detection composite** (`services/detection-engine/scoring.py`, `WEIGHTS_VERSION`): named `rule` / `statistical` / `model` components, a missing component dropped + renormalised (`scoring_status` → `degraded`); carried on the `DetectionPayload`. **Entity threat score** (`services/correlation-engine/scoring.py`, `CHAIN_SCORE_VERSION = "v1"`, Phase 7): a fixed documented weighting over severity + anomaly + threat-intel + attack-chain progression + chain confidence; asset-criticality and identity-risk are accepted as inputs and renormalise the weighting when supplied (no registry feeds them yet — their absence is not a fabrication). `correlation-engine` is now the **sole writer** of `threat_score` (one row per `(tenant, subject_type, subject_id)`, with `components` + `weights_version` + `scoring_status` for auditability) — `detection-engine` no longer writes it. `test_scoring.py` in both services (fixed inputs → fixed output, boundary `[0,1]`, renormalisation, degraded flag). No validated scoring performance claimed anywhere. A max-across-active-chains / time-decay entity score is deferred.

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
- **Phase:** P6. **Status:** IMPLEMENTED (CI-verified). `sm_contracts.threatintel` (`ThreatIndicator` / `ThreatActor` / `TiCampaign` / `TiSource` / `EnrichmentMatch` / `Provenance` / `TiUpdatePayload` on `ti.updates`; `IndicatorType` / `IndicatorFreshness` / `TiConfidence` / `TiSourceKind` / `TiUpdateAction`; `normalize_indicator_value` **rejects a malformed value (`ValueError`), never fabricates** (TB-4); `indicator_dedup_key` global-vs-tenant; `freshness_for`). `services/threat-intel-service` (port 8007): `IndicatorRepository` is the IOC system of record — dedup on `indicator_dedup_key`, first/last-seen widened, deterministic rule-based `reputation_score` (fixed base-by-confidence + tag deltas, clamped), freshness derived on read, `sweep_expired` + a background `ExpirySweeper` that emits `ti.updates` (`expired`); `ProviderAdapter` (`ThreatIntelProvider → ProviderAdapter → ExternalProvider`: per-call `asyncio.wait_for` timeout, backoff retry, HTTP 429 handling, malformed-row **drop-and-log** never ingested, outage → `ProviderResult(ok=False)` + metric); `FixtureProvider` labelled `source_kind=FIXTURE` and deterministic; `abusech` / `otx` external adapters feature-flagged off (`SM_TI_PROVIDERS` empty by default); a `ProviderPoller` background task upserts + emits `ti.updates` + records `ti_source`. Internal API `POST /api/v1/ti/{enrich,indicators}` + `GET /indicators` (internal-JWT, tenant from token; a bad value → 422). Every indicator carries a `Provenance` (provider, `source_kind`, reference, `retrieved_at`). `test_reputation.py` / `test_publish.py` / `test_api.py` / `test_providers.py`; `tests/integration/test_ti_store_pg.py` (upsert/dedup global vs tenant, enrich hit/miss/expired/malformed, list scope, sweep) + `test_ti_poller_pg.py` (fixture poll upserts + emits + records `ti_source`) + `test_ti_enrichment_chain_pg.py` (a seeded global IOC → the `normalization-engine` `ThreatIntelEnricher` over the real `/enrich` → `canonical.enrichment["threat_intel"]` → `detection-engine` `rule.ti.known_bad_indicator` with a `ti_indicator` evidence item; an unknown value produces no match and no hit).

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
- **Phase:** P8. **Status:** IMPLEMENTED — pipeline real, **no benchmark verified**. `sm_ml.graph`: `GraphSample` (deterministic, numpy-free node features from the edge set + a temporal window; a malformed sample raises `ValueError`, never repaired), versioned `GraphFeatureSchema` (`GRAPH_FEATURE_SCHEMA_VERSION = "1"`). Always-available structural path (stdlib, deterministic — the ADR-013 degraded path): `StructuralGraphAnomaly` (MAD z-score with a stdev dispersion floor), `SuspiciousSubgraphHeuristic` (score in `[0,1]`, never a certainty), `ConnectedComponentClusterer` / `LabelPropagationClusterer` (threat-cluster discovery). GNN boundary: `GnnNodeAnomalyModel` + `GRAPHSAGE_SPEC` / `GAT_SPEC` — `sm-ml[gnn]` (torch + torch-geometric) optional and **not in CI**; torch absent → `GraphModelUnavailable`, checkpoint absent → `GraphModelNotTrained`, the serving layer degrades to the structural path. `GraphModelRegistry` over `SM_ML_GRAPH_MODEL_DIR` (empty → nothing available; also loads a calibrated `structural_zscore` artifact). `services/ml-training` — the reproducible `dataset → … → evaluation` pipeline (offline CLI `sm-ml-train`), seeds + `config_hash` (byte-identical artifacts) + `ModelMetadata` (dataset id + sha256, versions, git commit) + `EvaluationReport` whose `headline_metrics` is `NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION` and `benchmark_verified` is `false` for a fixture run; `graphsage`/`gat` → `PipelineSkipped` without torch, no fabricated model/metric. `ml-inference` serves the graph models (`POST /api/v1/infer/graph/{model}` — structural always, GNN → 503 `MODEL_UNAVAILABLE` when unavailable; `GET /api/v1/graph/models`). `graph-service` `GET /api/v1/graph/intel` runs the structural models over a bounded, tenant-scoped neighbourhood. `ml/models/{graphsage,gat,graph_anomaly}/CONTRACT.md` per §6. `packages/ml-py/tests/{test_graph_construct,test_graph_models}.py`, `services/ml-training/tests/test_pipeline.py`, `services/ml-inference/tests/test_infer_graph.py`, `services/graph-service/tests/test_intel.py`, `tests/integration/test_graph_intel_neo4j.py` (real Neo4j — a fan-out hub is flagged, one cluster). **No accuracy / AUC / precision / recall number is claimed anywhere.** GPU + real dataset remain external requirements before any benchmark claim.

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
- **Phase:** P8. **Status:** IMPLEMENTED (library; CI-verified). `sm_ml.temporal` — standard-library, deterministic. `TemporalEvent` (source time + ingest time + entities + session). `EventTimeline` — a `bisect`-ordered stream keyed on `(effective_time, event_id)`: **duplicates** dropped by `event_id` (counted), **out-of-order** events inserted in order regardless of arrival (the same set of events always yields the same timeline), **clock skew** clamped to `ingested_at + SM_TEMPORAL_MAX_CLOCK_SKEW_SECONDS` (counted), **missing** events tolerated with `gaps()` reporting long silences. `TemporalGraphState.from_timeline(...).at(t)` — the graph as it stood at any past moment, a pure fold; `.to_sample()` → a `GraphSample` so a graph model can score history (chronological reconstruction). `build_progression(timeline, stage_fn)` — furthest kill-chain `AttackStage` over time (never regresses, records every transition). `replay(timeline, from_t, to_t)` + `ReplayCursor` — deterministic, read-only, windowed re-emission in effective-time order (side-effecting replay stays the caller's concern via `replay_group`). `stitch_sessions(sessions, link_within_seconds=SM_TEMPORAL_SESSION_LINK_SECONDS)` — union-find over "shares an entity **and** is within N seconds" → `StitchedTrack`s (cross-session correlation). `packages/ml-py/tests/test_temporal.py` (12). A streaming `temporal-stitcher` job and a `graph-service` `GET /timeline/{entity}` endpoint are deferred to when the read/UI surface (Phase 9) needs them.

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
- **Phase:** P4. **Status:** IMPLEMENTED (P9). `frontend/web` (Next.js 15 App
  Router) ships the SOC dashboard, alerts / incidents, attack-chain list + detail,
  MITRE ATT&CK heatmap, risk heatmap, entity explorer + timeline, threat-intel
  view, and an interactive Cytoscape attack-graph explorer with a node/edge detail
  panel and an accessible list fallback. Every view is typed from
  `@sentinelmesh/contracts` (generated), has loading / error / empty states, and
  labels demo/absent data honestly. **Deviations from the P4 architecture, all
  deliberate:** realtime is an honest client **poll** with a "last updated"
  indicator, not a WebSocket — `api-gateway` exposes no push channel for the
  Kafka-borne `graph.events` / `detections` topics yet, and `notification-service`
  is not built (later phase); "cinematic replay" is not implemented (the
  `sm_ml.temporal` replay engine from P8 is the backend foundation). Route guard
  is redirect-only in the browser; **authorization stays server-authoritative**
  in `api-gateway` (`require_permission`). Tests: 37 vitest component / API-contract
  / auth-flow / graph-interaction tests; no Playwright yet.

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
- **Phase:** P6. **Status:** IMPLEMENTED (P10, Unit 3). `services/ai-analyst`
  (`sm_ai_analyst`, port 8010, HTTP-only). `IncidentAnalyst.explain` builds an
  evidence bundle (every telemetry-/third-party-derived item fenced as data +
  injection-scanned), runs `sm_ai.build_grounded_messages` + `sm_ai.LlmClient`,
  and **validates that every `[ref]` the summary cites is a real evidence ref**
  (one repair turn). `sm_contracts.Explanation` per §7.2. `api-gateway`
  `GET /api/v1/soc/detections/{id}/explanation`. **Deviations, all deliberate:**
  no live LLM has been called (no credentials, ADR-014) — `HttpLlmBoundary` is
  written to the Anthropic Messages shape but never executed; with no key the
  analyst returns a **deterministic factual template** (`degraded=true`). It does
  **not** consume `detections` / `attack_chains` for pre-generation (on-demand
  only) and does **not** persist to a Postgres `explanation` table yet.
  `recommendations` are a fixed vetted per-subject list, never model-authored.
  Tests: 15 (grounding kept, ungrounded / unknown-ref fallback, injection flagged
  but answered, provider-outage → template, context rejected, route authz + 404 +
  503). No Playwright / no live-provider fixture.

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
- **Phase:** P8 (foundation) → P13 (interfaces). **Status:** IMPLEMENTED (P13)
  — **as deterministic heuristics, explicitly not a trained model.** Phase 8
  delivered the pieces a trained model would sit on (`sm_ml.temporal`,
  the GNN node-embedding boundary); Phase 13 delivers the four interfaces
  this row calls for — `sm_ml.predict` (`MODEL_VERSION = "heuristic-v1"`):
  `predict_attack_progression` (next kill-chain stage), `predict_next_action`
  (a technique the subject used before, not yet in this chain),
  `predict_lateral_movement` (fingerprint technique-overlap similarity, not
  a live graph traversal), `predict_threat_trajectory`
  (escalating/active/stalling/concluded from a campaign's status + chain
  count) — every one returns `{prediction, confidence, evidence, features,
  model_version, generated_at}` and `confidence=0.0` with a stated reason
  when underdetermined, never a guess. `memory-service`
  `POST /api/v1/predict/{attack-progression,next-action,lateral-movement,
  threat-trajectory}`, proxied at `/api/v1/soc/predict/...`.
  **Deviations, all deliberate:** no MLflow/S3, no trained sequence model, no
  training run — `{predicted_action, probability, horizon, confidence}`'s
  literal shape and a GPU-trained model remain future work; `horizon` is not
  produced (every prediction is "next", not "in N hours"); hosted on
  `memory-service`, not `ml-training`/`ml-inference`/`detection-engine` — the
  heuristics read threat-memory data those services don't own.
  **No accuracy, precision, or recall figure is claimed anywhere.**

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
- **Phase:** P9. **Status:** IMPLEMENTED (P12). **Deviations, all deliberate:**
  decoys live in `services/simulation-service` (not a separate
  `deception-service`) — `DecoyRepository` over Postgres `decoy` /
  `decoy_interaction` (migration `0007`); `network_boundary` is
  schema-**and**-DB-CHECK-constrained to `isolated` / `dmz-isolated` —
  `'production'` is not a legal value at either layer, which is the isolation
  invariant this row calls for. No `adversary_profile` table / clustering —
  that piece is genuinely not built (adversary profiling was optional in the
  original spec). API is
  `POST/GET/DELETE /api/v1/deception/decoys...` (role-gated via
  `deception:manage`, proxied through `api-gateway`'s SOC BFF at
  `/api/v1/soc/deception/...`), not an admin-only surface — this build has no
  separate "admin API" tier yet. Export is one-way (`POST .../interactions`
  captures, nothing pushes data back out); decoys carry no credential field at
  all, so "limited credentials" is "no credentials." Teardown is idempotent;
  interaction history survives it for audit. `frontend/web/app/(soc)/deception`
  — register / list / teardown / view interactions, badged "SIMULATION".
  **Not verified:** no decoy has faced a real attacker; a k8s network-policy
  isolation test is out of scope for this build (there is no k8s deployment
  yet) — isolation here is enforced by the data model, not a network boundary.

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
- **Phase:** P9. **Status:** IMPLEMENTED (P12). `sm_ml.scenario` — four
  deterministic templates (apt / ransomware / insider / brute_force) run
  against a seeded `SyntheticEnvironment` (every entity id `sim-`-prefixed);
  `validate_spec` raises `ScenarioIsolationError` unless every target is a
  synthetic id present in that env — a real-looking id is refused before a
  single event is produced. `services/simulation-service`
  `POST /api/v1/sim/scenarios/run` (proxied at
  `/api/v1/soc/simulation/run`, role-gated via `simulation:run`) runs a
  scenario; every emitted `SimEvent` carries `simulated=True` + its
  `scenario_id`. With `feed_pipeline: true`, `pipeline.py` produces the events
  onto the real `telemetry.raw` topic with `source.type = "simulation"` — so a
  drill exercises real normalization → detection → correlation → graph,
  labelled at every hop — never a code path to an external system.
  `replay_run` gives a deterministic read-only slice of a completed run.
  **Same-seed runs are byte-identical** (test-asserted). **Deviations:** no
  separate `simulation` / `simulation_run` / `scenario` Postgres tables — a
  run's events are returned in the response and, if requested, streamed into
  the existing telemetry pipeline; nothing about a run is persisted
  server-side today (a gap, not a safety issue — decoys and their
  interactions *are* persisted). `frontend/web/app/(soc)/simulation`, badged
  "SIMULATION".
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
- **Phase:** P4. **Status:** IMPLEMENTED (P11). `sm_contracts.QueryPlan` (closed
  schema) → `graph-service` `hunt.py` `validate_plan` + `compile_plan` (one
  constant parameterized Cypher template per intent; only a checked label /
  checked relationship type / clamped int depth are ever interpolated; every
  entity value is a `$`-param; `$tenant` from the verified token, no plan field
  for it) → `POST /api/v1/graph/hunt`. `api-gateway` `POST /api/v1/soc/hunt`
  (`require_permission(hunt:query)` + CSRF, tenant from the session `Principal`);
  `hunt_query` (migration `0006`) is the append-only audit trail.
  `frontend/web/app/(soc)/hunt` — an "Ask" NL mode and a "Quick query" structured
  form, both showing the **compiled `QueryPlan`** for transparency, with a "Pivot"
  action (runs `list_related` on a result row). **Deviations, all deliberate:**
  no Postgres/Neo4j full-text search, no saved queries, no `.../search` endpoint —
  entity lookup is by natural key via `find_entity`; the endpoint is
  `/api/v1/soc/hunt` not `/api/v1/hunt/query`. Tests: plan-validation, Cypher-
  injection-in-a-value stays a `$`-param, real-Neo4j tenant isolation +
  cross-tenant + hallucinated-entity, `/soc/hunt` authz + CSRF + no-tenant-field.

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
- **Module/File:** `packages/common-py/src/sm_common/bus/` (`producer`, `consumer`, `processor`, `admin`), `sm_contracts.topics`, `services/stream-processor/`, `scripts/{provision_topics,replay}.py`, `deploy/docker` (Redpanda).
- **Database:** Flink state + S3 checkpoints; Kafka topics.
- **API:** N/A.
- **Event:** the entire topic taxonomy (`event-model.md §3`); at-least-once; **exactly-once NOT claimed**.
- **Frontend:** N/A (ops dashboards in R23).
- **ML/AI:** N/A — NOT REQUIRED BY ARCHITECTURE.
- **Infrastructure:** Kafka/Redpanda, Flink (JDK 11+ — **external, absent locally**), Redis, S3.
- **Security boundary:** TB-3; SASL_SSL + ACLs in prod; per-key tenant isolation in state.
- **Test:** DLQ tests, consumer-lag/backpressure tests, checkpoint-restore tests, ordering tests, replay tests.
- **Verification method:** integration tests with Redpanda; Flink job tests (mini-cluster) — **EXTERNALLY DEPENDENT** (needs JDK 11+/Flink).
- **Phase:** P2 (Kafka), P3 (backbone). **Status:** **IMPLEMENTED + INTEGRATION VERIFIED** for the Kafka transport; stateful (Flink-class) jobs deferred per-job (ADR-010).
  - **Topic strategy / partitioning / ordering / versioned types:** `sm_contracts.topics` — the 12-topic catalog, `partition_key = sha256(tenant:entity)[:16]`, per-partition ordering only, `EVENT_TYPE_VERSION` + the `.v2` suffix policy. `test_topics.py`.
  - **Producer / consumer / consumer groups:** `sm_common.bus` — idempotent producer (`acks=all`), manual-commit-after-side-effect consumer with fetch-position rewind on failure, one group per logical consumer.
  - **Retries / DLQ / poison messages:** `RecordProcessor` — `PoisonError` → DLQ now, `TransientError` → exp backoff ×N → DLQ, wrapped `dlq_payload` to `<topic>.dlq` (event-model.md §5).
  - **Idempotency / duplicates:** deterministic downstream ids (`canonical_event_id`, `graph_command_id`); at-least-once, exactly-once **not claimed**.
  - **Replay:** `EventBusConsumer.seek_by_timestamp` + `scripts/replay.py` (dry-run default, `*-replay` group enforced).
  - **Graceful shutdown / backpressure / consumer lag:** `request_stop()` drains the in-flight batch; `SM_KAFKA_MAX_POLL_RECORDS` bound; `sm_consumer_lag` gauge.
  - **Topic provisioning:** `ensure_topics` / `scripts/provision_topics.py` (create + grow); compose `topics-init`, CI step.
  - **Observability:** `docs/architecture/observability.md` — metric catalog + DLQ-depth / lag alerts.
  - **All INTEGRATION VERIFIED** against real Redpanda: `tests/integration/test_bus_kafka.py` (9), `test_normalization_bus.py` (2), `test_stream_processor_bus.py` (2).

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
- **Phase:** P6. **Status:** IMPLEMENTED (P13). `services/memory-service`
  (port 8012) consumes `attack_chains` (group `memory`; the topic event is a
  thin projection, so `ChainsClient` fetches the full chain from
  `correlation-engine` first) and upserts three record kinds — never a
  shared "memory" table (ADR-011): `ThreatMemoryRow` (a behavioral pattern
  per subject, upserted — `occurrence_count` bumped, never one row per
  occurrence), `CampaignRow` (chains grouped by pgvector cosine similarity
  over a deterministic technique feature vector,
  `SM_MEMORY_CAMPAIGN_SIMILARITY_THRESHOLD`, exact-fallback on a DB error),
  `AdversaryFingerprintRow` (one evolving fingerprint per subject) — each a
  Postgres `vector(32)` column + `hnsw`/`vector_cosine_ops` index (migration
  `0009`, `pgvector/pgvector:pg16`). Produces `campaign.updates`.
  `POST /api/v1/memory/similar` (never returns the raw vector, only a
  score + `exact_fallback`) + read routes for patterns/fingerprints/
  campaigns, proxied by `api-gateway` at `/api/v1/soc/memory/...`
  (`memory:read`, migration `0010`). `RetentionSweeper` — the deletion
  lifecycle: `active -> dormant -> closed` on inactivity, then deleted past
  `SM_MEMORY_RETENTION_DAYS`. `frontend/web/app/(soc)/memory`. **Deviations:**
  `sm_ml.memory.technique_feature_vector` is a deterministic hashed
  bag-of-techniques, explicitly **not a trained embedding** — "ML/AI:
  embedding generation" above is satisfied by a documented rule, not a
  model. Cross-tenant similarity is not merely disabled by default — there
  is no code path to it at all (every query is `WHERE tenant_id = :tenant`);
  R34 (federated mesh) has not been built, so there is nothing to gate yet.

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
- **Phase:** P8 (architecture), **P14** (implementation). **Status:** IMPLEMENTED.
- **Deviation:** the LLM-generated narrative section (`ai-analyst`'s `/explain`)
  only fires when the report's subject *is* a detection — `ExplainRequest`'s
  subject type has no host/ip/domain/identity variant. For any other subject,
  `findings` is populated from deterministic content (technique mappings,
  memory-service patterns, a lateral-movement prediction) without an LLM
  pass, never fabricated in its place. Compliance-report role gating
  (`lead`/`tenant_admin`) is enforced in `api-gateway`'s route code on
  `kind == "compliance"`, not by a second permission code. There is no
  server-side report *listing* endpoint yet — only create-by-id and
  get-by-id; the frontend's "library" is session-local. Verified end to end
  against the real compose stack (real PDF uploaded to MinIO, downloaded via
  its presigned URL) rather than in CI (MinIO runs in CI too, but the E2E
  browser flow was exercised manually, not as an automated CI check).

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
- **Phase:** P1 (health/logging/request IDs), P8 (dashboards). **Status:** **PARTIALLY IMPLEMENTED / LOCALLY VERIFIED** — structured JSON logging with secret redaction, request/correlation IDs, the Prometheus registry with the standard counters, the OTel bootstrap (no-op without an endpoint), and `/healthz` `/readyz` `/health/deps` are implemented and unit-verified (Phase 1, Units 1-2-4). No metric has been scraped from a running Prometheus and no span has reached a collector — `NOT VERIFIED — REQUIRES EXTERNAL INFRASTRUCTURE`. Dashboards are P8.

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
- **Phase:** P4 (core), P8 (polish). **Status:** IMPLEMENTED (P9, core). Dark
  enterprise SOC shell (tenant-aware nav filtered by permission for display),
  responsive layouts, `prefers-reduced-motion` respected, severity encoded as
  colour + text + shape (WCAG 1.4.1), skip link, `role="status"` / `role="alert"`
  live regions, keyboard-operable graph via the list fallback. CSP + security
  headers in `next.config.mjs`; `react/no-danger` is an ESLint error; no secret in
  the bundle; session is an httpOnly cookie. **Deferred:** axe automation in CI,
  visual regression, Lighthouse budget checks.

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
- **Phase:** P9. **Status:** FOUNDATION IMPLEMENTED (P12) — **not fully
  implemented, stated plainly.** The engine a demo mode would drive now
  exists and is reachable end to end (R17's `simulation-service`, deterministic
  and clearly labelled `simulated`), so a guided demo could be built on top of
  it. **Not built:** a dedicated demo tenant, a guided walkthrough UI, or any
  "investor-ready" polish layer — `frontend/web/app/(soc)/simulation` is an
  operator tool (a form + a twin view), not a scripted demo experience. No
  "demo-flagged" scenario table exists (see R17's deviation note — no
  scenario table exists at all yet). Do not report this row as complete.

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
- **Phase:** P6 (analyst), P7 (agent actions). **Status:** IMPLEMENTED (P10). `packages/ai-py` (`sm_ai`) is the untrusted-LLM boundary: `LlmProvider` adapter (`DeterministicAdapter` + `HttpLlmBoundary`), `LlmClient` (token ceilings before any I/O, timeout, cancellation, transient-only retry, per-attempt audit -- prompt sha256 not raw), `ToolRegistry` (deny-by-default; an unauthorised/unknown tool call is rejected regardless of the LLM asking; every invocation audited), `EvidenceBuilder` + `fence_untrusted` + `scan_for_injection` (retrieved content is data, fenced), `build_grounded_messages` (evidence never in the system turn). `services/ai-analyst` runs the grounded analyst (`Explanation`, -7.2 -- every claim cites an evidence ref, one repair turn, else a deterministic template with `degraded=true`). **Deviations, all deliberate:** no live LLM has been called (no credentials, ADR-014) -- `HttpLlmBoundary` is inert without a key; on-demand only (no `detections` consumer for pre-generation); no Postgres `analyst_message` / `explanation` persistence yet; no analyst chat endpoint. Tests: grounding, injection, tool-authorization, "suggestion != action", audit emission, provider outage, timeout, budget.

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
- **Phase:** P7. **Status:** IMPLEMENTED (P10, Unit 4). `sm_ai.agents` -- `AgentSpec` (name + fixed system prompt + a tool **allow-list**), `run_agent` under hard limits (`max_steps`, `max_tool_calls`, `wall_clock_s`, a cumulative-token `RunBudget`, a cancellation `Event`). `DETECTION_AGENT` / `THREAT_INTEL_AGENT` / `RESPONSE_AGENT`. An agent **cannot spawn another agent** and **cannot execute** anything. A tool outside the agent's allow-list, or one the principal is not authorised for, is refused mid-run without stopping the run; a tool error is captured as a tool result, not a crash (failure isolation). The agent principal (`_AgentPrincipal`) holds **no standing permissions**. `services/ai-analyst` `POST /api/v1/agents/run`. **Deviations:** no `agent-orchestrator` service, no `agent.tasks` Kafka bus, no Postgres `agent_task` state, no inter-agent comms protocol -- a single flat agent run per request; no agent activity UI. Tests: allow-list boundary, unauthorised tool refused, step-limit, tool-call-limit, cancellation, wall-clock, budget.

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
- **Phase:** P7. **Status:** FOUNDATION IMPLEMENTED (P10, Unit 4). `sm_ai.agents.RESPONSE_AGENT` emits `ProposedAction`s (never executed) and `sm_ai.action_gate(action, response_mode, approval_required, is_production, policy_signed)` decides: `suggest_only` -> `denied`; `auto` still needs no approval requirement **and** production **and** a signed policy **and** a reversible action to be `allowed` -- otherwise `approval_required`. With `SM_RESPONSE_MODE=suggest_only` (the default) and `SM_RESPONSE_APPROVAL_REQUIRED=true`, an agent proposal is **never** `allowed`. An LLM proposing an action is never sufficient. **Deviations:** no EDR/firewall/SOAR adapters, no `response_action` / `response_policy` / `approval` tables, no `POST /api/v1/response/actions` execution endpoint, no blast-radius or rollback computation -- proposals + the gate verdict only. **Real endpoint isolation / firewall change: NOT VERIFIED -- REQUIRES ACTUAL INTEGRATION + VERIFIED ENVIRONMENT.** Tests: the `action_gate` truth table, "suggestion != action", irreversible-action-needs-review.

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
- **Phase:** P6. **Status:** IMPLEMENTED (P11). `ai-analyst` `HuntPlanner`
  (`POST /api/v1/hunt/plan`) — the LLM emits **only** a `QueryPlan`, parsed into
  the closed `sm_contracts.QueryPlan` model; non-JSON / invalid intent / no LLM →
  `PlanResponse(supported=false)`. **The LLM output is never used as a query in
  any form.** `graph-service` `hunt.py` is the deterministic compiler
  (parameterized templates, allow-listed labels/rel-types, `$tenant` from the
  token). `api-gateway` `POST /api/v1/soc/hunt` orchestrates plan → compile →
  execute → grounded explain; `hunt_query` (`0006`) is the audit trail. Constraint
  **RESOLVED** (ADR-015). **Deviations:** endpoint is `/api/v1/soc/hunt` (not
  `/api/v1/hunt/nl`); no dedicated Neo4j read-only role (the driver + the fixed
  read-only templates are the guarantee); no live LLM has been called
  (deterministic adapter only, ADR-014) — with no key an NL hunt is `unsupported`.
  Tests: "the model's output can only ever become a `QueryPlan` or `unsupported`",
  plan-validation, injection-in-NL, injection-in-a-selector-value stays a
  `$`-param, real-Neo4j tenant isolation.

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
- **Phase:** P6 (narrative), P9 (cinematic polish), **P14** (implementation).
  **Status:** IMPLEMENTED.
- **Deviation:** "incident" is `correlation-engine`'s own attack-chain id —
  this platform has no separate `Incident` entity yet (§3 still lists one
  PLANNED). A `NarrativeBeat`'s factual fields (`stage`, `detection_ids`,
  `technique_ids`) mirror `ChainStageModel` exactly and are deterministic,
  never touched by the LLM; only the one `summary` paragraph is LLM-composed,
  grounded by the same citation-and-retry mechanism `IncidentAnalyst.explain`
  (R14) uses. `simulated`/`GroundingKind.synthetic` is the contract-level form
  of the "label `SIMULATION`" requirement — verified end to end with a real
  simulation-sourced chain narrating as `synthetic` throughout.

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
- **Phase:** P9. **Status:** IMPLEMENTED (P12). `sm_ml.twin` — `TwinModel`
  (`TwinAsset` + `TwinRelation` + `TwinWeakness`, deterministic stdlib, no
  ML/GNN involved despite the row's original "ML/AI" note — this is a
  structural graph, not a learned model, so there is nothing probabilistic to
  state uncertainty for). `attack_paths` (bounded simple paths, feasibility =
  product of relation weights), `blast_radius` → reached set + per-hop
  distance + a criticality-weighted `score` ∈ [0,1] + amplifying weaknesses,
  `stress_test` + `DefensiveControl` → which paths a control set breaks + the
  most valuable control. `sm_ml.twin.synthetic.twin_from_synthetic_env` reads
  the twin directly off the same `SyntheticEnvironment` a scenario runs
  against — no separate, independently-maintained asset inventory to drift
  from reality. `services/simulation-service`
  `GET /api/v1/sim/twin` + `POST /api/v1/sim/twin/blast-radius` (proxied at
  `/api/v1/soc/simulation/twin` + `.../blast-radius`, role-gated via
  `simulation:run`); `frontend/web/app/(soc)/simulation` renders the asset /
  relation / weakness table and a per-asset blast-radius view. **Deviations:**
  no `digital_twin_model` Postgres table — the twin is a pure function of a
  seed, computed on read, not stored; there is no twin over anything but the
  synthetic environment (no real-asset digital twin exists in this build).
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
- **Phase:** P6. **Status:** IMPLEMENTED (P13). Relationship to
  R19/R21/R15/R29: **RESOLVED** (ADR-011) — and held to in the build:
  `AdversaryFingerprintRow` introduces no store beyond what R21 already
  owns (no separate `campaign_similarity` table — a fingerprint's own
  `campaign_ids` list is that link), and `predict_lateral_movement` (R15) is
  a straight consumer of R21's fingerprints, nothing new. `"seen before"` is
  the fingerprint lookup on `frontend/web/app/(soc)/memory`. **Deviations:**
  no separate `ai-analyst-service`/`agent-orchestrator` consumer wired up
  yet — the retrieval + prediction API exists and is real, but nothing
  automatically surfaces "similar past campaigns" inside an AI-analyst
  explanation in this build; that integration is future work.

### R23a — HTTP hardening (foundation)
- **Note:** not a numbered architecture requirement; recorded because Phase 1
  implemented it. Body-size cap, security headers, restrictive CORS (prod
  wildcard rejected at config validation), request/correlation IDs, and
  **per-caller fixed-window rate limiting** (`RateLimitMiddleware`, keyed on the
  resolved client IP, fails open with `sm_rate_limiter_errors_total`). Implemented
  and unit-verified (`services/api-gateway`, `packages/common-py`); the
  window-TTL behaviour has an integration test that is **skipped** for want of
  Redis.

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
- **Phase:** P1 provides local `docker-compose` + auth/RBAC/SSO foundation; full P38 hardening runs across late phases. **Status:** ARCHITECTURE DEFINED. The **RBAC and SSO foundation is IMPLEMENTED / LOCALLY VERIFIED** (Phase 1, Units 3-4): permission catalogue and system roles seeded by migration `0002`, deny-by-default `require_permission`, server-side principal resolution, per-request privilege re-resolution, and the OIDC authorization-code + PKCE client. Verified only against in-memory fakes — no real IdP, no cluster. Kubernetes/Helm remains `NOT VERIFIED — REQUIRES EXTERNAL INFRASTRUCTURE`.

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
