# SentinelMesh — Implementation State

**This file is authoritative for "where we are" and "what to do next".**
Update it at the end of every coherent implementation unit.

---

## Current phase

**Phase 15 — Observability + Benchmarking + Evaluation. COMPLETE (Unit 4
commit pending CI; Units 1-3 CI-VERIFIED — Unit 1 run `34698614073`,
commit `7eee2c1`; Unit 2 run `34699923546`, commit `80a0996`; Unit 3 run
`34701469455`, commit `498b98b`; see exit report below).** ADR-020 already specified OpenTelemetry + Prometheus + Grafana +
Loki; this phase closes the gaps between that spec and what actually runs.
Unit 1: real per-request tracing — every service already bootstrapped an
OTel `TracerProvider` (Phase 1) but nothing ever opened a span or set the
event envelope's `trace_id`, so the field was silently always `None`. New
`sm_common.fastapi.TracingMiddleware` opens a real server span per HTTP
request (W3C context extract/inject); `current_trace_id()` reads it (`None`,
never fabricated, when no real OTel provider is configured — the ubiquitous
local-dev/CI case). Wired into all 14 services' middleware stacks and into
both true envelope-origin points (`ingestion-gateway`, `simulation-service`).
`sm_common.bus.RecordProcessor` now opens a consumer span per Kafka record,
linked to the envelope's `trace_id` via a new `remote_context_from_trace_id`
(a `NonRecordingSpan` remote parent — the envelope carries a bare trace-id,
not a full `traceparent`, so there is no real parent span-id to restore).
Two previously-missing metrics: `sm_db_pool_{size,checked_out,overflow}`
(refreshed from the real SQLAlchemy pool at every `/metrics` scrape, wired
into all 10 Postgres-backed services) and `sm_neo4j_query_duration_seconds`
(wired into `graph-service`'s `Graph` client, the only service with a direct
Neo4j connection). Model-inference latency/DEGRADED, detection latency, and
graph-growth rate turned out to already be real and wired
(`ml-inference`'s `InferenceMetrics`, `detection-engine`'s `DetectionMetrics`,
`graph-service`'s `GraphMetrics`) — not duplicated. `sm_false_positive_
feedback_total` is registered but has no producer yet: no analyst "mark as
false positive" action exists anywhere in this build (a SOC-workflow
feature, not an observability one) — reports a real, honest `0`, not wired
to a fabricated signal. `/health/deps` (ADR-020/R23 named it for every
service; only `api-gateway` had it) added to the other 13 — the detailed,
never-503 dependency view, reusing each service's already-tested `_checks`/
readiness computation (two services — `mitre-service`, `simulation-service`
— had extra dependency entries appended only inside `/readyz`; refactored
into a shared `_status()` helper so `/health/deps` is not a narrower view).
`deploy/prometheus/prometheus.yml` scraped only `api-gateway`; added the
other 13 services as real scrape targets.
Local: ruff + `mypy --strict` clean (392 files, full CI static tree), **924
unit tests** (from 883: metrics/tracing/tracing-middleware/bus-processor
unit tests in `packages/common-py`, a `/health/deps` assertion added to
every service's existing health tests, 3 new `test_health.py` files for
`memory-service`/`reporting-service`/`simulation-service`, a new deploy-config
contract test asserting scrape-target/compose-port parity for all 13
services) + `gen_contracts.py --check` (no drift — no contract touched this
unit). Full real-infra `tests/integration` suite (**169 tests**, real
Postgres/Redis/Neo4j/Redpanda/MinIO) green. `Dockerfile.app` builds; every
service entrypoint + `sm_common.fastapi`/`observability` + `opentelemetry.
propagate` import clean in the image; non-root uid confirmed. Manually
verified against the real compose stack (not just `TestClient`): rebuilt
the image, brought up `api-gateway` + `ingestion-gateway` + real Prometheus,
confirmed a real `/health/deps` 200 with live dependency latencies, a real
`sm_db_pool_size` sample in `/metrics`, no fabricated `traceparent` response
header (no collector configured), and Prometheus's own `/api/v1/targets`
reporting both running services `up` on the new scrape config (the other 11
targets correctly `down` — DNS lookup failure — because those containers
simply were not started for this check, not a config defect).
Unit 2: the tabular IDS benchmark harness core (R24), distinct from the
existing graph-model training pipeline (Phase 8). New `services/ml-training/
src/sm_ml_training/benchmark/` — `nsl_kdd.py` (dataset adapter; categorical
columns one-hot encoded against a vocabulary derived from the train split
itself, never a hardcoded list, with an explicit `__unknown` bucket for a
category the test split has that train did not), `metrics.py` (stdlib-only
ROC-AUC — the Mann-Whitney-U tie-averaged rank form, verified against
analytic perfect-separation/perfect-reversal/tied cases — + precision/
recall/F1/false-positive-rate; deliberately no numpy/sklearn, so the metric
computation itself is auditable, not a library black box), `harness.py`
(`run_benchmark` — fits `sm_ml.models.StatisticalModel`, the platform's own
always-available detector, on the **benign-only** subset of the train
split — modeling "normal" behavior, exactly how `detection-engine` actually
uses it in production, ADR-013 — then scores the full labeled test split;
`BenchmarkRun` records dataset id + both file sha256s, preprocessing
version, split sizes, model + params, seed, every metric, and the real
environment). New CLI subcommand: `python -m sm_ml_training benchmark
--dataset nsl-kdd --train <path> --test <path>`.
**Real, executed run (2026-09-12, against the actual locally-staged
`KDDTrain+.txt`/`KDDTest+.txt`):** train sha256 `1b86d2f9...`, test sha256
`fa46b093...`, 125,973 train rows (67,343 benign used for the fit), 22,544
test rows (12,833 anomalous) -> **ROC-AUC 0.639039, precision 0.581191,
recall 0.681914, F1 0.627537, false-positive rate 0.649367, mean detection
latency 0.054062 ms/row.** Reported exactly as measured — a univariate MAD
z-score baseline against a diverse real-world-derived dataset is genuinely
this modest, and no tuning was done to make it look better (Constitution
§3). **Dataset-availability finding:** of the phase's named examples
(CICIDS2017/UNSW-NB15/LANL), only NSL-KDD is present locally in a usable
*labeled* form — CICIDS2017 was never downloaded (only a `.md5` stub),
UNSW-NB15 is only raw unlabeled partial Argus/BRO captures, and LANL has no
paired `redteam.txt` ground truth staged; their adapters and any benchmark
claim are deferred to Unit 3, pending an actual labeled copy — **no number
is claimed for any of them.** New `ml/datasets/nsl-kdd/MANIFEST.md` (format,
license, staging convention, column schema — matches the `ml/models/*/
CONTRACT.md` documentation style).
Local: ruff + mypy --strict clean, **26 new unit tests** (`test_benchmark_
metrics.py`, `test_benchmark_nsl_kdd.py`, `test_benchmark_harness.py` —
including a reproducibility test that separates the deterministic metrics
from the real, run-to-run-variable wall-clock timing field rather than
asserting timing equality). MLflow experiment tracking and a Postgres
`benchmark_experiment` table are explicitly deferred (Unit 4) — this unit
follows `ml-training`'s existing artifact-on-disk precedent, not a new
cross-service Postgres write path.
Unit 3: the baseline IDS comparison R24 asks for. `run_benchmark`'s `model`
parameter gained `"isolation_forest"` — scikit-learn's `IsolationForest`
trained directly in the harness (a genuine second, independently-implemented
method, not a relabeling of the statistical one), fit on the same
benign-only train rows, scored one row at a time against the same test
split — matching `sm_ml.models.AnomalyModel`'s real one-event-at-a-time
serving contract rather than an unrealistic batch score that production
never takes. Absent `sm-ml[serving]`, `run_benchmark(model="isolation_
forest")` raises `ModelUnavailable` (never silently degrades or fabricates
a result) — verified with a real test that blocks the import via
`monkeypatch`, mirroring `sm_ml.graph.models.gnn`'s existing
optional-dependency test convention. New `ml-training[benchmark]` extra
(`sm-ml[serving]`) added to all three `ci.yml` install blocks — unlike the
GNN/torch boundary, this dependency is light enough to install in CI, so
the comparison is exercised by CI's own fixture-based tests, not only by
hand locally.
**Real, executed comparison** (same NSL-KDD files/hashes as Unit 2):
Isolation Forest → **ROC-AUC 0.935499, precision 0.961297, recall 0.621289,
F1 0.754769, false-positive rate 0.033055, mean detection latency
24.836165 ms/row.** Head-to-head against Unit 2's statistical baseline
(ROC-AUC 0.639039, FPR 0.649367, latency 0.054062 ms/row): Isolation Forest
is substantially more accurate (AUC +0.296, FPR 20x lower) but ~460x slower
per row — a real, measured accuracy/latency tradeoff. Re-checked local
dataset availability for CICIDS2017/UNSW-NB15/LANL — unchanged from Unit 2
(none locally usable in labeled form) — so no adapter was built for any of
them this unit either; still no number claimed for any of them.
Local: ruff + mypy --strict clean, **4 new unit tests** (reproducibility,
"a genuinely different method not a relabeling", the real `ModelUnavailable`
path, an unknown-model-name `ValueError`) — 30 total in `ml-training/tests`.
Unit 4 (phase close): Grafana provisioning, benchmark-result storage +
read path, and a real bug found by actually running the new dashboard.
`deploy/grafana/provisioning/{datasources,dashboards}` auto-provisions the
Prometheus datasource + a 14-panel "Platform Overview" dashboard (real
PromQL against every metric inventoried this phase — HTTP rate/latency,
dependency health, Kafka lag/DLQ, Postgres pool, Neo4j latency, graph
growth, detection latency/degraded, model inference latency, rate limiting,
authn/authz, audit failures). Real bug caught bringing it up for real: a
second bind mount nested inside the first's target directory
(`.../dashboards/files`) fails on Docker Desktop ("read-only file system"
creating the nested mountpoint) — fixed by moving the dashboard JSON under
the one `provisioning` mount instead of a second volume. New Postgres
`benchmark_experiment` table (migration `0014`, no `tenant_id` — research
data, not tenant data) + `sm_ml_training.benchmark.persist.
save_benchmark_run` (plain `asyncpg`, new `ml-training[persist]` extra —
`ml-training` stays an offline CLI, not a server) + a new `--save-to-db`
CLI flag. `api-gateway`'s `SqlBenchmarkRepository` reads it directly
(mirroring `SqlSocRepository`/`ContentRepository`'s established precedent
for a BFF reading a table its owner exposes no HTTP read API for) via
`GET /api/v1/soc/benchmarks` (+ `/{id}`), gated on `ops:read` (only
`platform_operator` actually holds it in the real seeded RBAC). New
frontend `/benchmarks` page.
**A second real bug, found only by actually running the finished dashboard
against a live service, not by reading code:** `Metrics.observe_http` —
declared, scraped, and dashboarded since an earlier phase — had no caller
anywhere in the entire platform; `sm_http_requests_total`/`sm_http_
request_duration_seconds` had never once been incremented, on any service,
ever, since whichever phase first wrote that class. Fixed with a new
`sm_common.fastapi.MetricsMiddleware` (reads `services.metrics` from
`app.state` at request time — it does not exist yet when `add_middleware`
runs), wired into all 14 services. One narrow, verified, documented gap:
a fully unhandled `Exception` (a real bug, not a normal `SmError` path)
is recorded with status `0` rather than the real `500` the client
receives; every intentional error response is unaffected.
**Real, executed end-to-end proof (not a mocked link anywhere):** ran the
real CLI benchmark against the real NSL-KDD file with `--save-to-db`
pointed at the real compose-network Postgres; logged in as a real seeded
`platform_operator` user (created via direct SQL, cleaned up afterward —
`audit_log`'s FK blocked the tenant row's deletion, left in place
deliberately, matching established precedent); `GET /api/v1/soc/
benchmarks` returned the exact real row just inserted, ROC-AUC 0.639039
visible in the JSON body. Separately confirmed via `curl` against
Grafana's own API that the real datasource and the real dashboard are
loaded, and via a real Prometheus query that `sm_http_requests_total` now
carries real, just-served-request samples.
Local: ruff + mypy --strict clean (402 source files), **961 unit+contract
tests** (from 956: `test_metrics_middleware.py` — 5 tests, including one
that documents the unhandled-`Exception` status-0 gap explicitly rather
than asserting something false), `gen_contracts.py --check` clean (101
JSON Schema files, +1 `BenchmarkExperiment`), frontend gauntlet green
(eslint clean, 68 vitest tests across 18 files, `npm run build` — 22
routes incl. `/benchmarks`, `contracts-ts` typecheck clean), 3 new
real-Postgres integration tests (`test_benchmark_persist_pg.py` +3,
`test_benchmark_repository_pg.py` +3 — both had to switch from the
`database` fixture to `clean`, since `database` alone does not guarantee
the ORM-declared schema exists for that specific test run), full
`tests/integration` suite green (175 tests) after a genuine environmental
anomaly (a stale, session-long-accumulated Redpanda/Neo4j state caused one
unrelated graph-pipeline test to fail; root-caused by reproducing it in
isolation, then fixed by recreating both containers with fresh volumes —
not a code regression). `Dockerfile.app` builds; non-root uid confirmed;
every service entrypoint + `sm_common.db.benchmark_models` import cleanly.
**This closes Phase 15** — see the exit report below.

**Phase 14 — Reporting + Attack Storytelling. COMPLETE / CI-VERIFIED (all
five jobs, final run `34641513223`; see exit report below).** Every
generated narrative distinguishes ACTUAL SYSTEM EVIDENCE from INFERENCE
from PREDICTION from SYNTHETIC DEMO DATA (Constitution §3, `GroundingKind`)
— never a fabricated incident. Unit 1: `sm_contracts.report`
(`GroundingKind`, `GroundedStatement`, `Report`, `ReportGeneratedPayload`),
`sm_common.db.report_models` + migration `0011` (`report`/`report_template`,
seeded default templates per `ReportKind`), new `sm_common.objectstore`
(ADR-019 — `ObjectStore`/`safe_key`/`ensure_bucket`, async `aioboto3`,
MinIO-locally/S3-in-prod). Unit 2: `services/reporting-service` (port
8013) — gathers content from every dependency `service-catalog.md` names,
renders a PDF (`reportlab`), uploads via `sm_common.objectstore`, produces
`report.generated`; a missing content dependency lands in `missing_sections`
-> `partial`, never fabricated; only an object-storage failure produces
`failed`. Unit 3: attack storytelling in `services/ai-analyst` (R33) —
`NarrativeComposer` builds deterministic `NarrativeBeat`s straight from the
attack chain (never LLM-touched) plus one grounded summary paragraph reusing
`IncidentAnalyst.explain`'s citation-and-retry mechanism; a
simulation-sourced chain (`sm_ml.scenario.is_synthetic_id`) narrates with
every beat tagged `GroundingKind.synthetic` and `Narrative.simulated=True`
— the contract-level form of Phase 12's "SIMULATION" badge. ai-analyst
gained its first database (`narrative` table, migration `0012`) and first
cross-service call. Unit 4: `api-gateway` `routes/reports.py` —
`reports:read`/`reports:generate` enforcement (migration `0013`, widens
`permission.code`), a compliance-report role gate (`lead`/`tenant_admin`)
enforced in route code on top of the permission check, `requested_by`
always server-derived from the session principal, never trusted from the
client body; `frontend/web/app/(soc)/reports` (builder/library/lookup) and
`.../story` (chain narrative view), both using a shared `GroundingTag`
component. Real external-infra finding this phase: Docker Hub's
`minio/minio` repository started refusing anonymous pulls of the pinned
release tag — a genuine registry-side change (confirmed via a local repro
and a CI rerun, not transient), fixed by repointing compose + CI at
`quay.io/minio/minio` (same publisher, identical image digest). See the
Phase 14 exit report for full detail — **this closes Phase 14.**

**Phase 13 — Threat Memory + Predictive Intelligence. COMPLETE /
CI-VERIFIED (all five jobs, final run `34591054542`; see exit report
below).** Three distinct stores, one graph database
(`docs/ARCHITECTURE_DECISIONS.md` ADR-011): the operational graph and the
persistent knowledge graph both stay in Neo4j (`graph-service`); **threat
memory** is new this phase — Postgres + pgvector, owned by `memory-service`,
analytical/vector state, never a graph or a duplicate of the operational
detection/chain tables. Unit 1: `sm_ml.memory.technique_feature_vector`
(deterministic, L2-normalized, hashed-bag-of-techniques — **not a trained
embedding**, no semantic claim beyond "shared techniques land closer
together") + `cosine_similarity` (the Python exact-match fallback for when
pgvector is unavailable). `sm_common.db.memory_models` — `ThreatMemoryRow`
(a behavioral pattern per subject, upserted), `CampaignRow` (a set of related
attack chains), `AdversaryFingerprintRow` (one evolving fingerprint per
subject) — each with a `pgvector` `vector(32)` column and an `hnsw` /
`vector_cosine_ops` index (migration `0009`, `CREATE EXTENSION vector`).
`sm_contracts.memory` (`ThreatMemory` / `Campaign` / `AdversaryFingerprint` /
`SimilarityMatch` / `CampaignUpdatePayload` — moved out of `api/` in Unit 2 to
match `chains.py`'s placement of an entity + its own topic payload together)
— the raw feature vector is never returned over the API, only a similarity
score. The Postgres image (compose + CI) is now `pgvector/pgvector:pg16`
(ADR-006 already specified pgvector; this is the first phase that needs it).
A real-Postgres integration test (`tests/integration/test_memory_models_pg.py`)
proves a DB-side pgvector nearest-neighbor query and the Python fallback
agree on ordering, tenant scoping holds, and each CHECK constraint rejects an
out-of-vocabulary value. **No trained model, no fabricated similarity score —
a deterministic feature vector and real cosine distance, nothing more
claimed.** Unit 2: `services/memory-service` (port 8012) — consumes
`attack_chains` (group `memory`), fetches the full chain from
`correlation-engine` (the topic event has no technique data), upserts a
`ThreatMemory` pattern, matches-or-starts a `Campaign` (pgvector cosine
similarity, `SM_MEMORY_CAMPAIGN_SIMILARITY_THRESHOLD`, exact-fallback on a DB
error), upserts an `AdversaryFingerprint`, and produces `campaign.updates`.
`POST /api/v1/memory/similar` + read routes (`/patterns`, `/fingerprints/...`,
`/campaigns...`), internal-JWT only. A background `RetentionSweeper` ages a
campaign `active -> dormant -> closed` on inactivity and deletes patterns /
fingerprints / long-closed campaigns past `SM_MEMORY_RETENTION_DAYS` — the
deletion lifecycle the phase's memory-architecture section calls for. A
real-Postgres integration test (`tests/integration/test_memory_repository_pg.py`,
6 tests) caught a real bug: `Database`'s sessionmaker runs `autoflush=False`
platform-wide, so the retention sweep's in-memory campaign-status transitions
were invisible to the same-transaction DELETE that followed until an explicit
`flush()` was added. Unit 3: **prediction interfaces — no trained model
exists, every prediction is a deterministic heuristic and says so.**
`sm_ml.predict` (`MODEL_VERSION = "heuristic-v1"`) — `predict_attack_progression`
(the next kill-chain stage after a chain's furthest-reached stage, confidence
from the chain's own `confidence` + `distinct_stage_count`),
`predict_next_action` (a technique the subject has used before but hasn't
used yet in the current chain — grounded in that subject's own history, never
a guess about an unobserved technique), `predict_lateral_movement` (the other
recorded adversary fingerprint most similar by technique overlap —
cosine similarity, not a live graph traversal), `predict_threat_trajectory`
(escalating / active / stalling / concluded, from a campaign's own recorded
status + chain count). Every function returns `confidence=0.0` and says why
when the input does not support a prediction — never a guess dressed as a
result. `sm_contracts.api.prediction.Prediction` (`prediction`, `confidence`,
`evidence`, `features`, `model_version`, `generated_at` — `subject_type` is
`None` for the campaign-level `threat_trajectory`, which has no single
subject). `memory-service` gains `POST /api/v1/predict/{attack-progression,
next-action,lateral-movement,threat-trajectory}` (internal-JWT only),
wiring the heuristics to real data via the existing `ChainsClient` +
`MemoryRepository` (a new `list_fingerprints` method for lateral-movement
candidates). Unit 4: `api-gateway` `routes/memory.py` — the full BFF proxy
for threat-memory retrieval + predictions under `/api/v1/soc/{memory,
predict}/...`, new permission `memory:read` (migration `0010`, granted to
every role including `read_only` — read-only analytical information, unlike
Phase 12's operator-action permissions). `frontend/web/app/(soc)/memory` —
campaigns (+ predict trajectory), fingerprint lookup (+ predict lateral
movement), similarity search, chain predictions — every prediction rendered
with its confidence, evidence, and model version, never a bare verdict. See
the Phase 13 exit report for full detail — **this closes Phase 13.**

**Phase 12 — Simulation + Deception + Security Digital Twin. COMPLETE /
CI-VERIFIED (all five jobs, final run `34576850936`; see exit report
below).** Unit 1 (CI-verified, run
`34449930913`): `sm_ml.twin` — `build_twin(assets, relations, weaknesses) ->
TwinModel` (frozen, sorted, validated — deterministic, stdlib).
`attack_paths(twin, sources=, targets=, max_depth=)` (bounded, simple paths,
ordered by feasibility), `blast_radius(twin, seeds=, max_hops=, min_weight=)` →
`BlastRadiusReport` (reached set + per-hop + critical-assets-reached +
criticality-weighted score + amplifying weaknesses), `stress_test(twin, ...,
controls=[DefensiveControl])` → which attack paths a control set
(`block_relation_kind` / `isolate_asset` / `harden_asset`) would break, the
residual risk, and the single most valuable control. Unit 2 (CI-verified, run
`34569040279`): `sm_ml.scenario` — `build_synthetic_env(seed)` (deterministic,
every id `sim-`-prefixed, never real), `ScenarioSpec` (apt / ransomware /
insider / brute_force), `validate_spec` (raises `ScenarioIsolationError` unless
every target is a synthetic id present in the env), `run_scenario`
(deterministic ordered `SimEvent`s, each `simulated=True` + its `scenario_id`),
`replay_run` (deterministic read-only slice). Unit 3 (CI-verified, run
`34572530014`): `services/simulation-service` (port 8011) — `POST
/api/v1/sim/scenarios/run` runs a scenario against a fresh synthetic
environment built from the request's own seed and, when `feed_pipeline: true`,
produces every mappable event onto `telemetry.raw` (`source.type =
"simulation"`) via `pipeline.py`; `sm_contracts.api.simulation`
(`RunScenarioRequest` / `ScenarioRunResult` / `RegisterDecoyRequest` / `Decoy` /
`DecoyInteractionIn` / `DecoyInteraction`, `NetworkBoundary` excludes
`"production"`); the deception decoy registry (`/api/v1/deception/decoys...`,
`DecoyRepository` over Postgres tables `decoy` / `decoy_interaction`, migration
`0007`, `network_boundary` CHECK-constrained the same way at the DB level —
verified against real Postgres in `tests/integration/test_simulation_pg.py`);
idempotent teardown; a torn-down decoy captures no further interactions.
**Scenario execution and blast-radius analysis run against this model, never
against real systems.** Unit 4 (local green, awaiting CI):
`sm_ml.twin.twin_from_synthetic_env(env) -> TwinModel` (reads the twin off the
same synthetic environment a scenario runs against — a fixed role-dependency
graph, no separate asset inventory); `GET /api/v1/sim/twin?seed=` +
`POST /api/v1/sim/twin/blast-radius` on `simulation-service`; new permissions
`simulation:run` / `deception:manage` (migration `0008`); `api-gateway`
`routes/simulation.py` proxies scenario-run + twin + blast-radius + the full
deception decoy registry under `/api/v1/soc/{simulation,deception}/...`
(`require_permission` + CSRF on writes; a downstream `422` is now
`ValidationFailed`, not a misleading `DependencyUnavailable`);
`frontend/web/app/(soc)/{simulation,deception}`, both badged "SIMULATION". See
the Phase 12 exit report for full detail — **this closes Phase 12.**

**Phase 11 — Threat Hunting + Natural Language Querying. COMPLETE / CI-VERIFIED**
(all five jobs, final run `34448406595`; unit runs `34446018571` /
`34447606633`). Units 1-3 (`a9e4293` / `9cb52e1` / `9e07387`).
`frontend/web/app/(soc)/hunt` — an "Ask" NL mode and a "Quick query" structured
form, both showing the **compiled `QueryPlan`** for transparency, with a "Pivot"
action from a result row. `raw LLM output → executed Cypher` is
impossible: `sm_contracts.QueryPlan` is a **closed schema**, `ai-analyst`'s NL
planner only ever emits a `QueryPlan` (parsed into that model — never a query) or
says the request is out of scope, and `graph-service` `hunt.py` `validate_plan`
rejects anything outside the capability set then `compile_plan` maps each intent
to **one constant parameterized Cypher template** (only a checked label / checked
relationship type / clamped int depth are interpolated; every entity value is a
`$`-parameter; `$tenant` from the verified token, no plan field for it).
`POST /api/v1/graph/hunt` (Unit 1, CI-verified run `34446018571`).
`api-gateway` `POST /api/v1/soc/hunt` (`require_permission(hunt:query)`, tenant
from the session principal) orchestrates: `body.plan` → run directly; `body.query`
→ `ai-analyst` `/hunt/plan` (unsupported → `SocHuntResponse(supported=false)`,
never executed) → `graph-service` `/graph/hunt` → `ai-analyst` `/hunt/explain`
(grounded, best-effort). Every hunt recorded to `hunt_query` (migration `0006`,
append-only, tenant-scoped — stores what was asked + the answer shape, never the
result rows).

**Next: PHASE 12 — Simulation + Deception + Digital Twin (prompt not yet given —
do NOT start speculatively).**

**Phase 10 — AI Security Analyst + Multi-Agent Defense. COMPLETE / CI-VERIFIED**
(all five jobs, final run `34432159191`; unit runs `34429226626` / `34429715242`
/ `34430968254`). Units 1-4 (`90cc856` / `5b06de9` / `5f14fb3` / `908148b`).
`packages/ai-py` (`sm_ai`) is the untrusted-LLM boundary: provider-neutral
messages + `LlmProvider` (`DeterministicAdapter` default / `HttpLlmBoundary`
inert without a key, never called live), `LlmClient` (per-call token ceiling
before any network I/O, per-run `RunBudget`, timeout, cancellation,
transient-only retry, `AuditEvent` per attempt — prompt sha256 not raw),
`ToolRegistry` (deny-by-default; an unauthorised or unknown tool call is rejected
regardless of the LLM asking; input + output validation; audited), the injection
scanner + `fence_untrusted`, `EvidenceBuilder`, `build_grounded_messages`
(evidence never in the system turn), and `sm_ai.agents` (`AgentSpec` + tool
allow-list; `run_agent` under `AgentLimits` + a cancel `Event`; an agent cannot
spawn another agent, cannot execute, holds no standing permissions; `action_gate`
returns `denied` under the shipped `SM_RESPONSE_MODE=suggest_only`, never
`allowed`). `services/ai-analyst` (port 8010, HTTP-only) — grounded `Explanation`
(every claim cites an evidence ref; degraded template fallback) via
`GET /api/v1/soc/detections/{id}/explanation`, and `POST /api/v1/agents/run`.
See the Phase 10 exit report below. **The LLM is not trusted; it never gains a
privilege it was not already granted. No live LLM provider has been called.**

**Next: PHASE 11 — Threat Hunting + Natural Language Querying (prompt not yet
given — do NOT start speculatively).**

**Phase 9 — Enterprise SOC Dashboard. COMPLETE / CI-VERIFIED** (all five jobs
incl. `frontend`, final run `34428106928`). Units 1–4 (`15f5d1c` / `790fdf5` /
`dac8e50` / `3d8c401`). `frontend/web` (Next.js 15 App Router) ships every SOC
view — dashboard, alerts + `incidents/[id]`, attack-chain list + `chains/[id]`,
MITRE ATT&CK heatmap, risk heatmap, entity explorer + `entities/[id]` timeline,
threat-intel indicators, and an interactive Cytoscape attack-graph explorer with
a detail panel and an accessible node/edge list fallback. Every view is typed
from `@sentinelmesh/contracts` (generated — no backend shape re-declared), goes
through `DataView` (loading / error / empty / ready), and labels demo/absent data
honestly. Realtime is an honest client poll (`useResource` `refreshMs` +
`LiveBadge`) — no WebSocket yet, documented. Frontend auth is display-only;
`api-gateway` `require_permission` stays authoritative. See the Phase 9 exit
report below.

**Phase 8 — GNN + Temporal Intelligence. COMPLETE / CI-VERIFIED** (all four jobs,
runs `34408045416` / `34408494057` / `34409131977` / `34410178417`). Units 1–4.
Graph construction (`GraphSample`), the versioned `GraphFeatureSchema`, the
graph-model interface, the always-available structural path
(`StructuralGraphAnomaly` / `SuspiciousSubgraphHeuristic` /
`LabelPropagationClusterer` — stdlib, deterministic), the GNN boundary
(`sm-ml[gnn]` optional, `GraphModelUnavailable` without torch), `sm_ml.temporal`
(out-of-order / clock-skew / duplicate-safe timeline, replay, session stitching),
`services/ml-training` (the reproducible pipeline on a synthetic fixture),
`ml-inference` `POST /api/v1/infer/graph/{model}`, `graph-service`
`GET /api/v1/graph/intel`. No metric is fabricated —
`METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION` everywhere.

**Phase 7 — Attack Chain Reconstruction + Threat Scoring. COMPLETE / CI-VERIFIED**
(all four jobs, run
[`34406870398`](https://github.com/gaurav685/sentinelmesh/actions/runs/34406870398)).
Units 1–3.
Unit 3: `correlation-engine` also emits `graph.commands` (`graph.py` — `:AttackChain`
node + `INVOLVES` → subject + `MAPPED_TO` → `:AttackTechnique`, deterministic
`command_id` per chain). `mitre-service` now consumes `attack_chains` too (one
group, dispatch on `event_type`; a chain's mapping subject is `attack_chain`).
`detection-engine` stops writing `threat_score`; `correlation-engine` is the sole
writer. Topic registry updated. Real-infra e2e (`test_chain_pipeline_e2e_pg.py`):
auth burst → detection → chain + one `threat_score` row (`weights_version = "v1"`)
+ a `:AttackChain` node in real Neo4j with `INVOLVES` → `:Identity` and
`MAPPED_TO` → `:AttackTechnique`. Phase 7 exit report + §23 below;
`REQUIREMENTS_TRACEABILITY` R6 → IMPLEMENTED, R8 updated.
Unit 2: `services/correlation-engine` (port 8009, module `sm_correlation_engine`,
consumer group `correlation`). Consumes `detections`; `staging.py` places each
detection on the furthest kill-chain `AttackStage` its techniques imply (no
technique → `unknown`, never guessed; a `rule.ti.*` detection marks the chain
TI-corroborated); `chains.py` `ChainRepository.correlate` upserts the
deterministic-id chain + its `attack_chain_stage` rows (detection ids as a set →
idempotent on redelivery; `min`/`max` timestamps → out-of-order safe; `ti_corroborated`
monotonic); `scoring.py` recomputes `progression`, probabilistic `confidence`
(≤ 0.95, discounted when stages ran backwards in time), `ChainStatus`, and a
versioned deterministic `score` (`CHAIN_SCORE_VERSION = "v1"`) over severity /
anomaly / threat-intel / progression / confidence (+ optional asset-criticality /
identity-risk that renormalise the weighting — no registry feeds them yet);
`engine.py` emits `AttackChainPayload` on `attack_chains` (poison → DLQ, DB /
produce failure → retry); read API `GET /api/v1/chains[/{id}]` (internal-JWT,
tenant from token). Wired into `Dockerfile.app` / compose (`detect` profile) / CI
(13th mypy tree, installs, image import). Migration `0005` amended (additive
columns `attack_chain_stage.max_detection_score`, `attack_chain.ti_corroborated`).
Unit 1: `sm_contracts.chains` — `AttackStage` (14 ATT&CK-tactic kill-chain stages
+ `unknown`), `STAGE_ORDER`, `TACTIC_STAGE` / `TECHNIQUE_STAGE` deterministic
lookups (`stage_for_tactic` / `stage_for_technique`; a technique with no known
mapping → `unknown`, never guessed), `ChainStatus` (forming/active/dormant — never
auto-`confirmed`), `ChainStageModel`, `AttackChainModel` (read DTO),
`AttackChainPayload` on `attack_chains` (`EventType.attack_chain_updated`),
`chain_dedup_key` / `chain_window_start` (fixed tumbling window → deterministic
under redelivery + out-of-order) / `chain_id_for`. `confidence` is capped at
`CONFIDENCE_CEILING = 0.95` — a chain never claims certainty. Alembic `0005` +
`sm_common.db.chain_models` (`attack_chain`, `attack_chain_stage`; CHECK
constraints from the contract enums, deterministic id, `(tenant, subject,
window_start)` unique, stage unique per chain, CASCADE). `DetectionPayload` gained
optional `subject_type` / `subject_id` (populated by `detection-engine`, consumed
by the correlator). Config: `SM_CHAIN_WINDOW_SECONDS`, `SM_CHAIN_DORMANT_SECONDS`,
`SM_CHAIN_SCORE_ALERT_THRESHOLD`, `SM_CORRELATION_ENGINE_URL`.

**Phase 6 — Threat Intelligence + MITRE ATT&CK. COMPLETE / CI-VERIFIED**
(all four jobs, run
[`34366970151`](https://github.com/gaurav685/sentinelmesh/actions/runs/34366970151)).
Units 1–5. Pipeline:
`detections → mitre-service → technique_mapping` (Postgres) and
`events.canonical → normalization-engine ThreatIntelEnricher → threat-intel-service
POST /enrich → canonical.enrichment["threat_intel"] → detection-engine
rule.ti.known_bad_indicator + ti_indicator evidence`. Phase 6 exit report + §23
review below.
Unit 5: `normalization-engine` `ThreatIntelEnricher` (feature-flagged
`SM_TI_ENRICHMENT_ENABLED`, default off; IP / domain / hash lookups; a TI-service
outage leaves `enrichment` absent, never fails the event — R2) + `detection-engine`
`rule.ti.known_bad_indicator` (severity from match reputation, `technique_ids=()`,
`EvidenceItem(kind=ti_indicator)` with provenance) + `test_ti_enrichment_chain_pg.py`
(seeded global IOC → real enrich API → detection with TI evidence; no-match path).
Unit 4: `sm_ti_service.providers` — the `ThreatIntelProvider → ProviderAdapter →
ExternalProvider` architecture (per-call timeout, backoff retry, HTTP 429 handling,
malformed-row drop, outage → `ok=False` + metric), a `FixtureProvider` (labelled
`source_kind=FIXTURE`), stubbed `abusech` / `otx` adapters (feature-flagged off;
`SM_TI_PROVIDERS` empty by default), and a `ProviderPoller` background task that
upserts + emits `ti.updates` + records `ti_source`.
Unit 3: `services/threat-intel-service` (req 9, TB-4) — IOC store of record
(`threat_indicator` etc.), dedup on `indicator_dedup_key` (global vs tenant),
rule-based deterministic `reputation_score`, freshness derived on read, a
background expiry sweep that emits `ti.updates` (`expired`), internal API
`POST /api/v1/ti/{enrich,indicators}` + `GET /indicators`, `TiUpdatePayload` on
`ti.updates` per add/update. Never fabricates: a malformed value is rejected
(422), every indicator carries a `Provenance`, fixture data is
`source_kind = FIXTURE`.
Unit 2: `services/mitre-service` (req 7) — Postgres catalog store,
`scripts/import_attack_stix.py` + `stix.py` (STIX 2.1 → tactics/techniques/matrix
version; a labelled fixture bundle drives tests; **no ATT&CK data ships**), a
rule-based `MappingEngine` (validates a detection's candidate `technique_ids`
against the imported catalog — unknown → `unmapped`, never guessed; deprecated →
`unmapped`), consumes `detections` → `technique_mapping` upserts, internal API
`GET /api/v1/mitre/{techniques,heatmap}` + `POST /map`, `/readyz` flags an empty
catalog. Unit 1: `sm_contracts.mitre` (`AttackTactic` /
`AttackTechnique` / `AttackMatrixVersion` / `TechniqueMapping` / `TechniqueMatch`;
`MappingConfidence` / `MappingSource` / `MappingSubjectType`) and
`sm_contracts.threatintel` (`ThreatIndicator` / `ThreatActor` / `TiCampaign` /
`TiSource` / `EnrichmentMatch` / `Provenance` / `TiUpdatePayload` on `ti.updates`;
`IndicatorType` / `IndicatorFreshness` / `TiConfidence` / `TiSourceKind` /
`TiUpdateAction`; `normalize_indicator_value` reject-not-fabricate,
`indicator_dedup_key`, `freshness_for`). Alembic `0004` + models for the eight
`mitre-service` / `threat-intel-service` tables.

**Phase 5 — Detection + Anomaly Detection. COMPLETE / CI-VERIFIED.** Units 1–5,
all four CI jobs green on a clean runner: runs
[`34353986031`](https://github.com/gaurav685/sentinelmesh/actions/runs/34353986031)
/ [`34355234014`](https://github.com/gaurav685/sentinelmesh/actions/runs/34355234014)
/ [`34356219219`](https://github.com/gaurav685/sentinelmesh/actions/runs/34356219219)
/ [`34357914090`](https://github.com/gaurav685/sentinelmesh/actions/runs/34357914090)
/ [`34358654888`](https://github.com/gaurav685/sentinelmesh/actions/runs/34358654888).
`events.canonical → detection-engine → detection / anomaly / threat_score /
security_alert (Postgres) → detections (Kafka)`. Trained models + any accuracy
figure are `NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`. Phase 5 exit
report + §23 review below. Unit 1:
`sm_contracts` detection domain + Alembic `0003` (`detection` / `anomaly` /
`threat_score` / `security_alert` — the `detection-engine` system of record).
Unit 2 (local verified): `packages/ml-py` (`sm_ml`) — versioned `FeatureSchema`
per `CanonicalKind` + deterministic numpy-free extractors, `Preprocessor`
(versioned standardisation), the `AnomalyModel` protocol + `StatisticalModel`
(MAD z-score, stdlib-only, the always-available / ADR-013 degraded path),
`IsolationForestModel` (sklearn, `sm-ml[serving]`), `AutoencoderModel`
architecture spec + `ModelNotTrained` guard, `ModelRegistry` (loads artifacts
from `SM_ML_MODEL_DIR`; missing dir = empty), and `ml/models/*/CONTRACT.md` (§6,
`METRICS: NOT VERIFIED`). Unit 3: `services/ml-inference` (ADR-013) — `ModelHost`
over the registry (lazy load + cache + `reload()`), internal-JWT `POST
/api/v1/infer/{model}` + `GET /api/v1/models`, a missing / unloadable / serving-
deps-absent model → HTTP 503 `dependency_unavailable` with `MODEL_UNAVAILABLE`
(never a 500, never a fabricated score), per-model latency + error + load
metrics, `/readyz` always ready (models optional). Unit 4: `services/detection-engine` —
consumes `events.canonical` (group `detection`); per event `extract_features` →
a per-`(tenant, kind)` `StatisticalModel` refit from an in-process rolling window
(adaptive thresholds) → `anomaly` row; optional `ml-inference` call, any failure
→ `scoring_status = DEGRADED` + statistical only (ADR-013); six deterministic
rule detectors (failed-auth burst, credential reuse, auth-then-egress lateral
movement, suspicious process cmdline, DNS tunnelling, NXDOMAIN burst) over a
time-bounded `EventTimeline`; deterministic composite score (`WEIGHTS_VERSION`,
renormalised over present components); a `detection` (deterministic id, upsert)
only when a rule fired at `medium`+ or the score crossed
`SM_DETECTION_SCORE_THRESHOLD`, every claim an `EvidenceItem`; a `security_alert`
at `high`/`critical` or score ≥ `SM_DETECTION_ALERT_THRESHOLD`; `threat_score`
upsert per subject; emits `DetectionPayload` on `detections`. Tenant-scoped
throughout; malformed / unknown-kind → DLQ; DB / produce failure → retried.
Wired into Dockerfile / compose (`detect` profile, port 8006) / CI (10th mypy
tree, installs, image import). Unit 5 (real-infra e2e + exit report) follows.

**Phase 4 — Neo4j + Graph Intelligence Foundation. COMPLETE / CI-VERIFIED.**
Units 1–4, all four CI jobs green on a clean runner: runs
[`34346140544`](https://github.com/gaurav685/sentinelmesh/actions/runs/34346140544)
/ [`34348143536`](https://github.com/gaurav685/sentinelmesh/actions/runs/34348143536)
/ [`34349655012`](https://github.com/gaurav685/sentinelmesh/actions/runs/34349655012)
/ [`34350607501`](https://github.com/gaurav685/sentinelmesh/actions/runs/34350607501)
(`integration` runs against real PostgreSQL + Redis + Redpanda + Neo4j 5). Write
path `graph.commands → graph-service → Neo4j`, read path `GraphRepository` +
`/api/v1/graph/*`, end-to-end from `events.canonical` verified. Phase 4 exit
report + §23 review below.
Unit 1 (run `34346140544`):
the Neo4j async driver wrapper, the label/relationship allowlist (Cypher-injection
guard), the versioned `.cypher` schema migration + runner, the production config
guard, and the compose/CI wiring for a Neo4j service. Unit 2 (local + integration
verified, CI pending): `services/graph-service` — the only write path into Neo4j;
consumes `graph.commands`, applies each as a parameterized idempotent MERGE,
emits `graph.events`. Units 3–4 (the graph-query API, the full integration set +
exit report) follow.

**Phase 3 — Kafka + Stream Processing. COMPLETE / CI-VERIFIED.** Units 1–4:
Unit 1 topic registry; Unit 2 bus hardening + topic provisioning; Unit 3
`RecordProcessor` + `stream-processor` (`graph-update-emitter`); Unit 4 ADR-010
decision (U-001/U-002 **resolved** — plain-Python for stateless, cluster engine
deferred per job), `scripts/replay.py`, `docs/architecture/observability.md`,
`REQUIREMENTS_TRACEABILITY` R3/R20, the Phase 3 exit report (below). **CI green
on a clean runner** (run
[`34342866073`](https://github.com/gaurav685/sentinelmesh/actions/runs/34342866073)).
Flink **not** implemented — no JDK 11+ locally (ADR-001), no stateful job's
consuming phase has arrived.

---

### Phase 4, Unit 2 — graph-service (the Neo4j write path) (DONE — local + integration verified)

- `services/graph-service` (port 8004, module `sm_graph_service`, consumer group
  `graph-writer`). Mirrors the `stream-processor` shape: a Kafka consumer with a
  health/metrics HTTP surface, no ingest. The lifespan owns the Neo4j driver, the
  producer, the consumer, and one `EventBusConsumer.run(RecordProcessor)` task.
- `GraphWriter.apply(GraphCommandPayload) -> MutationResult`:
  - **Parameterized Cypher only.** The single thing interpolated is a node label
    / relationship type, and only after `normalize_label` + membership check
    against `sm_contracts.GRAPH_NODE_LABELS` / `GRAPH_REL_TYPES`. Off-list → the
    engine raises `PoisonError` → `graph.commands.dlq`.
  - **Idempotent by `command_id`** — a read of the `_GraphCommand` ledger
    short-circuits a redelivery to `DUPLICATE` (no mutation). The ledger row is
    written *after* the (idempotent) MERGE, so a crash between the two just
    re-runs the MERGE on retry.
  - **Node key** must be exactly `{<key prop for label>: value}`; MERGE is keyed
    on the synthetic `graph_node_uid(tenant_id, value)` (`"<tenant>:<value>"`).
  - **Out-of-order safe** — every node/rel carries `_watermark` (newest
    `observed_at` applied). An older command widens `first_seen` / `last_seen`
    but does not overwrite props → `STALE`.
  - **Tenant invariants by construction** — `tenant_id` written everywhere; node
    uid embeds the tenant, so an edge can only join same-tenant nodes.
  - **Missing endpoint nodes** for a `MERGE_EDGE` are created thin.
  - **`MERGE (s)-[r:REL]->(e)`** on endpoints only → repeated commands update the
    one edge, never duplicate it.
  - `PRUNE` → `PoisonError` (the retention job is later).
- `GraphEngine.handle`: parse the `graph.command` envelope (bad → `PoisonError`),
  apply, `GraphUnavailableError` → `TransientError` (retry, never drop), then
  produce one `graph.events` record (`event_id == command_id`); a failed produce
  → `TransientError`.
- Contracts: `EventType.graph_event` (`"graph.event"` → topic `graph.events`),
  `GraphEventPayload` (`command_id, op, outcome ∈ APPLIED|DUPLICATE|STALE,
  tenant_id, observed_at, raw_event_id, label, nodes_written,
  relationships_written`), `GraphMutationOutcome`. Registered; 2 new JSON Schemas
  (38 total). `gen_contracts.py --check` clean.
- Metric `sm_graph_commands_applied_total{service,op,outcome}` (retry/DLQ/lag are
  the shared bus metrics).
- Wiring: `graph-service` added to `Dockerfile.app` (COPY + `pip install`),
  `docker-compose.yml` (`graph` profile, `depends_on` neo4j healthy, port 8004),
  CI (`static`/`unit`/`integration` installs, `mypy` 7th tree, `image` import
  check). `pyproject.toml` `known-first-party` += `sm_graph_service`.
- Tests: `services/graph-service/tests` — `test_writer.py` (10, fake graph:
  allowlist rejection, key validation, prune, duplicate short-circuit,
  parameterization, stale, edge), `test_engine.py` (6: envelope parsing, error
  mapping, one `graph.events` per command), `test_health.py` (4).
  `tests/integration/test_graph_service_neo4j.py` (6, real Neo4j via the `graph`
  fixture): tenant-scoped node creation, `command_id` no-op, out-of-order keeps
  the newer value, edge creation + both endpoints, no duplicate relationship,
  cross-tenant isolation (two nodes, zero cross-tenant edges). CI-green (run
  `34348143536`).

### Phase 4, Unit 3 — the graph-query API (DONE — local + integration verified)

- `sm_graph_service.repository.GraphRepository` — read-only, tenant-scoped,
  bounded queries:
  - `entity(tenant_id, label, key)` — one node's public props, or `None`.
  - `neighbors(tenant_id, label, key, depth=1, limit=None)` — a bounded
    neighbourhood as `{nodes, edges, truncated}`. Two parameterized reads (nodes,
    relationships), each `LIMIT $cap`.
  - `attack_path(tenant_id, src, dst, max_depth=4)` — `shortestPath` between two
    keyed nodes, projected to primitive node/edge dicts.
  - **Parameterized only.** The only interpolated values are an allowlisted node
    label (`ValidationFailed` → 422 otherwise) and an integer traversal depth
    clamped to `[1, SM_NEO4J_TRAVERSAL_MAX_DEPTH]` (default cap 8). Every path is
    `WHERE all(x IN nodes(p) WHERE x.tenant_id = $tenant)`. Row cap
    `SM_NEO4J_QUERY_MAX_ROWS` (default 1000). `_`-prefixed props + `uid` stripped.
- `routes/graph.py` — `GET /api/v1/graph/{entity,neighbors,paths}` on
  `graph-service`. `deps.get_principal` verifies the internal service JWT
  (`verify_internal_token`, audience `graph-service`) — **the tenant scope is the
  token's `tenant_id`, never a query field**. Bad / missing / wrong-audience /
  wrong-key token → 401. Missing entity → 404.
- Config: `SM_NEO4J_QUERY_MAX_ROWS` (1000), `SM_NEO4J_TRAVERSAL_MAX_DEPTH` (8).
  `.env.example` updated.
- Response models (`EntityResponse` / `NeighborsResponse` / `PathResponse`) are
  DRAFT and service-local (`schemas.py`) until the read surface settles.
- Tests: `test_repository.py` (9 — label rejection, depth clamp up + floor, row
  cap + `truncated`, param-not-in-cypher, `_public` stripping, path projection),
  `test_graph_api.py` (8 — 401 matrix, tenant-from-token, 404, 422, view shape).
  `tests/integration/test_graph_service_neo4j.py` +4 (real Neo4j: public-props
  only, bounded neighbourhood at depth 1 vs 2, shortest path length 2,
  cross-tenant reads return nothing). CI-green (run `34349655012`).

**Phase 2 — Telemetry Ingestion + Normalization. COMPLETE / CI-VERIFIED.**
Units 1–4 implemented; §23 review done; full compose stack + live end-to-end
verified; **CI green on a clean runner** (run
[`34333269219`](https://github.com/gaurav685/sentinelmesh/actions/runs/34333269219),
2026-09-09): `static` (ruff + `mypy --strict`), `unit` (268 tests + schema
`--check`), `integration` (63 tests — real PostgreSQL 16 + Redis 7 + Redpanda,
`0001 -> 0002` migrations), `image` (build of all four services + non-root +
entrypoint imports + prod fail-fast guards). Pipeline: sensor →
`ingestion-gateway` → `telemetry.raw` → `normalization-engine` →
`events.canonical` (poison → `telemetry.raw.dlq`).

Phase 1 exited INTEGRATION VERIFIED on local Docker; its CI jobs also went green
in the same run.

### Phase 3, Unit 3 — RecordProcessor + stream-processor (graph-update-emitter) (DONE)

- `sm_common.bus.RecordProcessor` — the shared retry / DLQ policy
  (event-model.md §4/§5). A domain handler raises `PoisonError` (→ DLQ now) or
  `TransientError` (→ exp backoff × `SM_KAFKA_HANDLER_MAX_ATTEMPTS`, then DLQ);
  anything else propagates (uncommitted → the consumer rewinds + redelivers).
  DLQ record is `dlq_payload(...)` to `dlq_topic(record.topic)`; meters
  `sm_consumer_dlq_total` / `sm_consumer_retries_total`.
- `normalization-engine` refactored onto it: `engine.handle` now only *signals*
  intent (raises `PoisonError` / `TransientError`); the hand-rolled parse→DLQ
  and produce-retry loops are gone. `NormalizationMetrics` dropped its
  `sm_normalize_dlq_total` / `sm_normalize_produce_errors_total` (the shared bus
  metrics cover it — no duplication).
- `sm_contracts.graph` — `GraphCommandPayload` (CONTRACTS.md §5:
  `command_id, op ∈ MERGE_NODE|MERGE_EDGE|SET_PROPS|PRUNE, tenant_id,
  observed_at, raw_event_id, label, key, props, start/end`), `GraphOp`,
  `GraphEndpoint`, `graph_command_id(raw_event_id, op, label, discriminator)`
  (deterministic). Registered for `EventType.graph_command`; 2 new JSON Schemas.
- `services/stream-processor` (port 8003) — a stateless stream job with a
  health/metrics HTTP surface. `emitter.emit(canonical_envelope)` maps one
  `events.canonical` event → a `MERGE_NODE` command per entity + one
  `MERGE_EDGE` `actor -[REL]-> target` (`REL` from `CanonicalKind`,
  `data-model.md` vocab; `EntityKind` → Neo4j label). Each command's envelope
  `event_id == payload.command_id`, deterministic in the source canonical
  `event_id`, so a redelivery re-emits identical commands (idempotent for
  `graph-writer`, Phase 4). `StreamEngine.handle` wrapped by `RecordProcessor`;
  `events.canonical` → `graph.commands`, poison → `events.canonical.dlq`.
  Metrics `sm_stream_{in,commands_out}_total`.
- Added to `Dockerfile.app` (one image), compose (`bus` profile,
  `depends_on: topics-init`), Makefile, CI (install + `mypy` + image
  entrypoint-import check).
- `.env` `SM_KAFKA_BOOTSTRAP_SERVERS` corrected to `localhost:19092` (Redpanda
  EXTERNAL listener; matches `.env.example`).
- Tests: `services/stream-processor/tests` (15 — emitter mappings, engine
  DLQ/retry/redelivery, health); `tests/integration/test_stream_processor_bus.py`
  (2, real Redpanda — canonical → graph commands with the right shape; poison →
  DLQ + next good still processes). `test_normalization_bus.py` updated for the
  `RecordProcessor` refactor.
- Verified: pytest **293** non-integration / **74** integration
  (`SM_REQUIRE_INTEGRATION=1`, Redpanda v24.2.11 + Postgres 16 + Redis 7),
  `mypy --strict` clean (122 files), `ruff` clean, `gen_contracts --check` clean,
  `docker compose --profile bus config` valid.

### Phase 3, Unit 2 — bus hardening + topic provisioning (DONE)

- `sm_common.bus.admin.ensure_topics(settings, specs?)` — `AIOKafkaAdminClient`
  create-if-absent from the registry's partition counts + retention, **and
  grows** a pre-existing under-provisioned topic (`create_partitions`; Kafka
  allows increasing only). `scripts/provision_topics.py` CLI (`--list`),
  `make provision-topics` / `make topics`, a compose `topics-init` one-shot that
  `normalization-engine` now `depends_on: service_completed_successfully`.
- `EventBusConsumer`:
  - **at-least-once on handler failure** — `run_once` now *rewinds the fetch
    position* to the batch start on any exception, so the same consumer
    redelivers on the next poll (aiokafka advances the in-memory position on
    `getmany`; the old code only redelivered after a rebalance/restart). This
    was a real gap — `test_offset_is_committed_only_after_the_handler_succeeds`
    proves the fix.
  - **graceful shutdown** — `request_stop()` (flag) lets the in-flight batch
    finish + commit; `stop()` waits on the batch lock then closes. The
    `normalization-engine` lifespan drives it with `SM_KAFKA_SHUTDOWN_GRACE_MS`.
  - **backpressure** — `SM_KAFKA_MAX_POLL_RECORDS` bounds in-flight records; no
    prefetch of the next batch until the current one commits.
  - **replay** — `seek_by_timestamp(when)` on all assigned partitions
    (event-model.md §6).
  - **lag** — after each poll, `sm_consumer_lag{group,topic,partition}` =
    `highwater - position`; plus `sm_consumer_records_total`.
- `EventBusProducer`: `flush()` on `stop()`; `linger_ms` from settings; a
  fast-fail + `sm_producer_send_errors_total{topic}` on a send that raises.
- `Metrics` gained `consumer_records` / `consumer_dlq` / `consumer_retries` /
  `consumer_lag` / `producer_send_errors`. Config: `kafka_linger_ms`,
  `kafka_max_poll_records`, `kafka_shutdown_grace_ms`, `kafka_handler_max_attempts`.
- `normalization-engine` passes `metrics` into its producer + consumer.
- Tests: `tests/integration/test_bus_kafka.py` (9, real Redpanda) — topic
  provision + grow, produce/consume, JSON round-trip, offset-commit-after-
  side-effect, at-least-once redelivery, graceful shutdown commits the in-flight
  batch, replay by timestamp, lag/records metrics, producer send-error metric.
  Verified: pytest 278 non-integration / **72 integration**, `mypy --strict`
  clean (108 files), `ruff` clean, `gen_contracts --check` clean.

### Phase 3, Unit 1 — topic registry + versioned event types (DONE)

`sm_contracts.topics`: `TopicSpec` (name, partitions, key, retention, cleanup,
producers, consumer_groups, `has_dlq`, `partitions_min`, `retention_ms`) and
`TOPICS` — the 12-topic catalog from event-model.md §3, verbatim. `EVENT_TYPE_TOPIC`
maps every `EventType` to its topic (`topic_for_event_type`); `dlq_topic(t)` =
`<t>.dlq`; `replay_group(g)` = `<g>-replay` (event-model.md §5/§6).
`EVENT_TYPE_VERSION` records the major version per type (all 1 today; a breaking
change adds a `.v2` member — the "versioned event types" policy, now also in
event-model.md §2). `ingestion-gateway` / `normalization-engine` now derive their
topic names from the registry (no string literals). `test_topics.py` (10 tests)
guards the mapping, the catalog invariants and the key partition counts.
Verified: pytest 278 non-integration / 63 integration, mypy --strict clean, ruff
clean, `gen_contracts --check` clean.

### Phase 2, Unit 1 — telemetry payload contracts (DONE)

`sm_contracts.telemetry`: `NetworkFlowPayload`, `AuthEventPayload`,
`DnsQueryPayload`, `ProcessExecPayload`, `FileAccessPayload` (sensor payloads,
IP-validated, free-text bounded, case-normalized, cross-field rules) and
`CanonicalEventPayload` + `EntityRef` (normalized view with `raw_event_id`
lineage). Registered in `EVENT_PAYLOAD_REGISTRY` and `SCHEMA_MODELS`;
`gen_contracts.py` emits 34 JSON Schema files. `test_telemetry.py` (13 tests).
Verified: pytest 32 (contracts-py) / 202 (non-integration), mypy --strict clean
(19 files), ruff clean, schema `--check` clean. Commit `ce2d616`.

### Phase 2, Unit 2 — sensor authentication + the ingestion gateway (DONE)

**Step 1 — `SensorAuth`.** `sm_common.security.sensor_auth`: `SensorAuth` /
`SensorIdentity`. Given a presented credential `<sensor_id>.<secret>` (optional
`Bearer ` prefix), it parses, looks up the `sensor` row, verifies the secret
against `credential_hash` with Argon2id (`dummy_verify` for an unknown / malformed
id so there is no timing oracle), then gates on `status == active` and
`deleted_at is null`. Every failure is one generic `Unauthenticated`; the reason
is never returned. `last_seen_at` is touched on success, throttled to one write
per 60s so a chatty sensor does not turn its registry row into a write hot-spot —
so `authenticate` runs inside `Database.transaction()`.

**Step 2 — `services/ingestion-gateway`.** FastAPI service (port 8001,
`python -m sm_ingestion_gateway`):

- `POST /api/v1/ingest/{source_type}` (`network_flow | auth_event | dns_query |
  process_exec | file_access`). Body is the bare payload; the envelope is built
  server-side (`envelope.build_envelope`) — `event_id` UUIDv7, `tenant_id` /
  `source.sensor_id` / `source.type=sensor` **from the `SensorIdentity` only**,
  `occurred_at` lifted from the payload, `producer=ingestion-gateway@0.1.0`,
  `partition_key = <tenant_id>:<primary entity>`. Built as the concrete
  `EventEnvelope[...]` so the sink serializes every payload field.
- `POST /api/v1/ingest/batch` — `{source_type, events:[...]}`, capped at
  `SM_INGEST_BATCH_MAX_EVENTS` (default 500); per-element failures come back in
  `rejected` and are dead-lettered, one bad event does not fail the batch.
- Status codes: `202` accept / `200` duplicate `X-Sensor-Event-Id` / `404`
  unknown `source_type` / `422` (+DLQ) bad JSON or failed schema / `401` any
  sensor-auth failure / `413` over `SM_HTTP_MAX_BODY_BYTES` / `503` limiter-store
  outage.
- `RateLimitMiddleware` gained a `fail_open` flag; the gateway passes
  `fail_open=False` so a Redis outage rejects (`503 dependency_unavailable`)
  instead of letting a flood through. No CORS middleware (sensors aren't
  browsers). No `/docs` in production.
- Idempotency: optional `X-Sensor-Event-Id` in a Redis `SET NX EX` keyed on
  `(sensor_id, id)`, TTL `SM_INGEST_DEDUP_TTL_SECONDS`. A Redis outage returns
  `DedupState.unavailable` and the event is still sinked (downstream is
  idempotent on `event_id`).
- `sinks.py`: `RawEventSink` / `DeadLetterSink` protocols. Unit 2 shipped
  logging stopgaps; Unit 3 (below) added the Kafka implementations behind the
  same interfaces.
- `/healthz`, `/readyz` (postgres + redis [+ kafka when the bus is on]),
  `/api/v1/meta`, `/metrics`
  (`sm_ingest_{accepted,rejected,duplicates,dedup_errors,sink_errors}_total`).

One image (`Dockerfile.app`) now builds both services; the compose `command:`
selects the entrypoint. `ingestion-gateway` is in the default compose profile.

Verified (2026-09-09): pytest **242** non-integration, **59** integration,
`mypy --strict` clean, `ruff` clean, `gen_contracts.py --check` clean.

### Phase 2, Unit 3 — Kafka producer behind `RawEventSink` (DONE)

- `sm_common.bus.EventBusProducer` (aiokafka) — the shared producer wrapper:
  `enable_idempotence=True` (⇒ `acks=all`), bounded `request_timeout_ms`, keyed
  `send_and_wait`, `start()`/`stop()` for the lifespan, `ping()` (forces a
  metadata refresh) for readiness. `from_settings` reads `SM_KAFKA_*`. ADR-004
  updated: **aiokafka** is the chosen client. aiokafka added to `sm-common`
  deps; `[[tool.mypy.overrides]]` for the missing stubs.
- `sm_ingestion_gateway.kafka_sinks`: `KafkaRawEventSink` → `telemetry.raw`
  (canonical JSON, keyed on `partition_key`), `KafkaDeadLetterSink` →
  `telemetry.raw.dlq` (raw body verbatim, `reason` / `source_type` / `sensor_id`
  in headers, keyed on sensor id).
- `build_services` picks the Kafka sinks + opens the producer when
  `SM_EVENT_BUS_ENABLED=true`, else the logging stopgaps. `create_app` refuses
  to start in production with the bus disabled. `/readyz` gains a `kafka` probe
  when the bus is on.
- Pipeline failure policy: a `raw_sink` produce failure → `503`
  `dependency_unavailable` (single and batch — batch aborts, sensor retries the
  whole batch, consumers idempotent on `event_id`), metered
  `sm_ingest_sink_errors_total{sink=raw}`. A `dlq_sink` failure is swallowed and
  metered `{sink=dlq}` so a second sink failure cannot turn a client 4xx into a
  5xx.
- `partition_key` conformed to `event-model.md`:
  `sha256(<tenant_id>:<primary_entity>)[:16]` (was a readable `<tid>:<entity>` —
  an unrecorded Unit 2 divergence, now fixed).
- compose `redpanda` given a dual listener (`INTERNAL://redpanda:9092`,
  `EXTERNAL://localhost:19092`) + healthcheck; CI `integration` job starts
  redpanda as a plain container (service containers can't take a start command).

Verified (2026-09-09): pytest **249** non-integration (7 new — `test_kafka_sinks.py`
4, sink-failure cases in `test_ingest.py` 3), **61** integration (2 new —
`tests/integration/test_ingestion_bus_pg.py`: accepted event round-trips through
`telemetry.raw`; malformed body lands on `telemetry.raw.dlq` with headers —
against real Redpanda + Postgres + Redis). `mypy --strict` clean (90 files),
`ruff` clean, `gen_contracts --check` clean. Compose stack + live end-to-end
verified later the same day — see "Verification performed (Phase 2, Units 2–4)".

### Phase 2, Unit 4 — normalization-engine (DONE)

- `sm_common.bus.EventBusConsumer` (aiokafka): the shared consumer wrapper.
  `enable_auto_commit=False`; `run_once()` handles a poll batch then commits;
  `run()` loops until `stop()`. `from_settings` reads `SM_KAFKA_CONSUMER_GROUP`.
  Plus `dlq_payload(...)` — the canonical DLQ record shape (event-model.md §5):
  original + `{error_type, error_detail, consumer_group, attempts, failed_at}`.
  (Distinct from the ingestion gateway's DLQ, which keeps the raw bytes verbatim
  + headers — a producer-side reject, not a consumer failure.)
- `services/normalization-engine` — a stream processor, HTTP only for health /
  metrics. Lifespan owns the producer, the consumer, and one background task
  running `consumer.run(engine.handle)`.
- `normalize/mappers.py`: one deterministic mapper per `telemetry.*` payload →
  `CanonicalEventPayload` (normalized verb, `actor`/`target` entity refs, full
  entity list incl. DNS answers as ip/domain, flat `attributes`). Lineage
  (`raw_event_id`, `raw_event_type`) and event time come from the source
  envelope. `enrich/` is a stub `Enricher` protocol + runner (empty provider
  list → `enrichment = {}`); a provider that raises is recorded partial, never
  fails the event.
- `engine.py` handler contract with the consumer: a **poison** record
  (unparseable / unknown `event_type` / invalid envelope / mapper bug) → DLQ,
  return (offset commits, partition keeps moving); a **produce** failure →
  retry×3 backoff, then raise (offset not committed, batch redelivered; the
  idempotent producer prevents partition dupes). Metrics
  `sm_normalize_{in,out,dlq,produce_errors}_total`.
- The canonical envelope: new `event_id`, `event_type=event.canonical`,
  `producer=normalization-engine@…`, `tenant_id`/`source`/`correlation_id`/
  `trace_id` copied from the source, `partition_key =
  sha256(<tenant_id>:<actor|target|first entity>)[:16]`,
  `metadata.raw_event_id` set.
- `partition_key` derivation extracted to `sm_contracts.make_partition_key` —
  the ingestion gateway now calls it too (was a private copy).
- `normalization-engine` added to `Dockerfile.app` (one image), compose (`bus`
  profile, `SM_EVENT_BUS_ENABLED=true`), Makefile, CI, isort config.

Verified (2026-09-09): pytest **266** non-integration (17 new —
`test_normalize.py` 6, `test_engine.py` 7, `test_health.py` 4), **63**
integration (2 new — `tests/integration/test_normalization_bus.py`: a
`telemetry.raw` network-flow record becomes an `events.canonical` envelope with
lineage; a poison record lands on `telemetry.raw.dlq` (wrapped) and the next
good record still processes — real Redpanda). §23 review added 3 regression
tests (deterministic canonical `event_id`; corrected-retry dedup; empty DNS
answer). `mypy --strict` clean (106 files),
`ruff` clean, `gen_contracts --check` clean. Compose stack (all 6 containers
healthy) + live end-to-end verified the same day — see "Verification performed
(Phase 2, Units 2–4)". NOT VERIFIED: CI.

### Phase 1 — INTEGRATION VERIFIED on local Docker (kept for the record)

Docker Desktop was installed on the development machine on 2026-09-09 (engine
29.7.2, WSL2 2.5.10). The full compose stack and the integration suite now run
here. The integration verification is done locally:

- `docker compose -f deploy/docker/docker-compose.yml up -d postgres redis` then
  `pytest tests/integration -q -m integration` with `SM_REQUIRE_INTEGRATION=1`:
  **52 passed** against real PostgreSQL 16 and Redis 7.
- Full stack `docker compose up -d --build`: the `migrate` container applied
  `0001 -> 0002` (exit 0); `app` returns `/healthz` 200, `/readyz`
  `{"ready":true}` with live postgres and redis probes, and `/api/v1/meta` 200.
- `docker build -f deploy/docker/Dockerfile.app`: builds; the image runs as uid
  10001; a production CORS wildcard is rejected inside the built image;
  `docker compose config` validates.

Four first-run defects were found and fixed (see the verification section for
Unit 6 — integration). The one remaining gap is the CI workflow: it needs a
GitHub remote and `gh auth login`, then `bash scripts/push_and_watch.sh`. The
local branch was renamed `master -> main` so the `on.push` trigger matches.

Phase 1 is treated as INTEGRATION VERIFIED on local infrastructure; the CI
`integration` and `image` jobs remain the independent confirmation and must run
before Phase 2 is itself declared complete.

## Phase 15 exit report

**State: COMPLETE (Units 1-3 CI-verified all five jobs each; Unit 4 commit
pushed, CI pending confirmation at time of writing — see "Exact next
action" for run ids).** Unit 1 `7eee2c1`, Unit 2 `80a0996`, Unit 3
`498b98b`, Unit 4 commit tracked in "Exact next action" once pushed.
Unit-level CI runs: 1 = `34698614073`, 2 = `34699923546`,
3 = `34701469455`, 4 = pending.

**ADR-020 already specified the observability stack; this phase closed
the gap between that specification and what actually runs, then built a
reproducible ML benchmark/evaluation system that never claims a number
until the benchmark is actually executed (Constitution §3).** Two real,
load-bearing gaps were found this phase not by reading code but by
actually running the finished feature against live infrastructure:
`trace_id` had been silently `None` on every event since the phase that
introduced it (nothing ever opened a span), and `Metrics.observe_http` had
never been called anywhere in the platform despite being scraped and
dashboarded. Both are fixed and verified with a real span/real metric
sample, not just a passing unit test.

### Delivered (Units 1-4)

| Area | State |
|---|---|
| Real tracing + the remaining metrics + `/health/deps` (Unit 1) | `sm_common.fastapi.TracingMiddleware` opens a real per-request OTel span (W3C extract/inject); `current_trace_id()`/`remote_context_from_trace_id()` wired into both true envelope-origin points and `sm_common.bus.RecordProcessor`'s Kafka-consumer span. `sm_db_pool_*` + `sm_neo4j_query_duration_seconds` (the two genuinely-missing metrics — model-inference/detection-latency/graph-growth already existed under each owning service's own metrics class). `/health/deps` added to the 13 services that lacked it. `prometheus.yml` scrape-target parity for all 13 previously-unscraped services. |
| Tabular benchmark harness + a real NSL-KDD run (Unit 2) | `sm_ml_training.benchmark` — dataset adapter (`nsl_kdd.py`, vocabulary derived from the train split itself), stdlib-only metrics (`metrics.py` — Mann-Whitney-U ROC-AUC, precision/recall/F1/FPR, no numpy/sklearn), the reproducible run (`harness.py` — `sm_ml.models.StatisticalModel` fit on benign-only train rows). Real, executed run: ROC-AUC 0.639039, F1 0.627537. |
| Baseline IDS comparison (Unit 3) | `run_benchmark(model="isolation_forest")` — scikit-learn's `IsolationForest` trained directly in the harness, scored one row at a time (matching `AnomalyModel`'s real serving contract). Real, executed run: ROC-AUC 0.935499, F1 0.754769 — substantially more accurate, ~460x slower per row than the statistical baseline, a real measured tradeoff. |
| Grafana + result storage + BFF/frontend + a second real bug (Unit 4) | `deploy/grafana/provisioning` — real datasource + 14-panel dashboard (a nested-bind-mount bug fixed after it actually failed on Docker Desktop). `benchmark_experiment` table (migration `0014`) + `save_benchmark_run` (plain `asyncpg`) + `--save-to-db` CLI flag. `api-gateway`'s `SqlBenchmarkRepository` (`GET /api/v1/soc/benchmarks[/{id}]`, `ops:read`) + frontend `/benchmarks` page. Found and fixed `Metrics.observe_http` never being called anywhere (`sm_common.fastapi.MetricsMiddleware`, all 14 services). |

### Verification performed (local + CI, 2026-09-12)

- `ruff check` clean over `packages services tests migrations scripts`;
  `mypy --strict` clean over the full CI static-tree list (402 source
  files by phase close).
- **961 unit+contract tests** by phase close (up from 883 at Phase 14's
  close: 41 in Unit 1, 26 in Unit 2, 4 in Unit 3, ~7 net in Unit 4 incl.
  `test_metrics_middleware.py`) + `gen_contracts.py --check` (101 JSON
  Schema files, +1 `BenchmarkExperiment`).
- Real infra: full `tests/integration` suite (175 tests by phase close)
  green against real Postgres/Redis/Neo4j/Redpanda/MinIO after every
  unit, including 6 new benchmark-persistence/repository tests. One
  environmental anomaly this phase (a session-long-accumulated
  Redpanda/Neo4j state failing one unrelated graph-pipeline test) was
  root-caused by isolated reproduction and fixed by recreating both
  containers with fresh volumes — confirmed not a code regression.
- `frontend/web`: `npx eslint .` clean, `npm run build` OK (22 routes,
  `/benchmarks` new), **68 vitest tests** across 18 files (up from 62),
  `contracts-ts` typecheck clean.
- `docker build -f deploy/docker/Dockerfile.app` builds; non-root uid
  10001 confirmed; every service entrypoint + `sm_common.db.
  benchmark_models` + `opentelemetry.propagate` import cleanly.
- **Real, executed end-to-end proof, every link real, none mocked:** ran
  the actual CLI benchmark against the actual NSL-KDD file with
  `--save-to-db` pointed at the real compose-network Postgres; logged in
  as a real seeded `platform_operator` user; `GET /api/v1/soc/benchmarks`
  returned the exact row just inserted. Separately: `curl`'d Grafana's own
  API and got back the real provisioned datasource and dashboard; queried
  Prometheus directly and got back real `sm_http_requests_total` samples
  matching a request just made through the real running `api-gateway`
  container.
- **CI green on a clean runner for Units 1-3 — all five jobs each** (runs
  `34698614073` / `34699923546` / `34701469455`). Unit 4's CI run id is
  recorded in "Exact next action" once confirmed.

### Pre-output engineering review (Constitution §23)

- **No fabricated measurement, anywhere, at any layer.** `current_trace_id()`
  returns `None` rather than a fake id when no real OTel provider is
  configured (the default local/CI state) — verified with a real assertion
  that no `traceparent` response header appears in that case. Every
  `BenchmarkRun`/`BenchmarkExperiment` traces back to `executed=True`,
  enforced by the table's own `CHECK` constraint, not just a convention.
  The two ROC-AUC numbers this phase reports (0.639039, 0.935499) came
  from real executions against a real, hash-recorded dataset file, with no
  tuning to make either look better.
- **A real gap, found by running the feature, not assumed fixed by
  writing it.** Both `trace_id` (Unit 1) and `sm_http_requests_total`
  (Unit 4) had existed as declared-but-dead code since earlier phases.
  Both were found only because the finished dashboard/feature was
  actually run against live infrastructure and the result was checked,
  not because a unit test passed — the standing practice this build
  follows throughout, applied again here.
- **Dataset-availability honesty over convenience.** CICIDS2017/UNSW-NB15/
  LANL are all present on the local machine but none in a genuinely usable
  labeled form — re-checked in Unit 3, unchanged from Unit 2's finding. No
  adapter was built for any of them, and no number is claimed for any of
  them, rather than quietly substituting a dataset that happened to be
  available.
- **Cross-service reads follow existing precedent, not a new exception.**
  `api-gateway`'s `SqlBenchmarkRepository` reads `benchmark_experiment`
  directly because `ml-training` (an offline CLI, not a service) exposes
  no HTTP read API — the same justification, and the same established
  pattern, `SqlSocRepository`/`ContentRepository` already use for
  `detection`/`threat_score`.
- **Permission checks verified against real seeded grants, not assumed.**
  `ops:read` is gated correctly — confirmed only `platform_operator`
  actually holds it in the real migration-seeded RBAC (not `tenant_admin`,
  despite an earlier test fixture's `admin_perms` including it — a
  pre-existing fixture breadth that predates this phase, left alone since
  fixing it was out of this phase's scope).

### Deferred (deliberately)

- **MLflow experiment tracking.** No MLflow server is deployed in this
  build; `BenchmarkRun`/`benchmark_experiment` carry everything a real
  tracking system would need (dataset hashes, params, seed, metrics,
  environment) the moment one exists.
- **CICIDS2017, UNSW-NB15, and LANL dataset adapters.** Not locally usable
  in labeled form (documented reasons above); building an adapter for data
  that cannot be genuinely evaluated would itself be a form of
  fabrication risk (untested code, unverifiable claims).
- **Loki/Tempo/Jaeger log/trace collectors.** No collector is deployed;
  spans and structured logs are real and ready to ship the moment one is
  configured (`SM_OTEL_EXPORTER_OTLP_ENDPOINT`).
- **The unhandled-`Exception` status-0 metric gap.** A genuinely unhandled
  exception (a real bug, not a normal error path) is recorded with status
  `0` rather than the real `500` the client receives — documented and
  tested as a known, narrow limitation rather than silently accepted or
  hidden; every intentional `SmError` response is unaffected.

### Exit criteria status

| Criterion | Status |
|---|---|
| Metrics, structured logs, tracing, health/readiness/liveness/dependency checks | ✅ real spans, real HTTP+DB-pool+Neo4j metrics, `/health/deps` on all 14 services |
| Prometheus / Grafana / OpenTelemetry integration | ✅ real scrape config, real provisioned datasource + dashboard, real OTel spans (no collector deployed — spans stay local, by design, until one exists) |
| Reproducible ML benchmark pipeline on architecture-approved datasets | ✅ NSL-KDD (real, executed); CICIDS2017/UNSW-NB15/LANL honestly deferred (not locally usable) |
| Never claim a number until the benchmark is actually executed | ✅ every metric in this phase's docs came from a real, hash-recorded, reproducible run |
| Baseline IDS comparison | ✅ Isolation Forest vs. the statistical baseline, real measured accuracy/latency tradeoff |
| Tests: metric collection, tracing, dashboard configuration, benchmark reproducibility, evaluation scripts, result storage | ✅ all covered — unit + real-Postgres + a real Grafana-API + real Prometheus-query verification |
| **CI green on a clean runner** | ✅ **Units 1-3, all five jobs each** (`34698614073` / `34699923546` / `34701469455`); Unit 4 pending confirmation |

## Phase 14 exit report

**State: COMPLETE / CI-VERIFIED (all five jobs, final run
[`34641513223`](https://github.com/gaurav685/sentinelmesh/actions/runs/34641513223)).**
Unit 1 `ea56100`/`c2e949a`/`a6c6cdd`, Unit 2 `d6b5269`, Unit 3 `d7525ff`,
Unit 4 `18c9e1f` + follow-up fix `a7b0704`. Unit-level CI runs: 1 =
`34597754999`, 2 = `34631135008`, 3 = `34635710315`, 4 = `34641513223`
(the first Unit-4 push, run `34640559225`, failed only on an external
Docker-Hub registry outage unrelated to code — see below; all five jobs
green after the fix).

**Every generated narrative distinguishes evidence from inference from
prediction from synthetic data (Constitution §3), across every layer that
touches one.** `GroundingKind` is not decoration on one contract — it is
threaded through `Report.evidence`/`findings`/`recommendations`
(`GroundedStatement`), `Narrative.beats` (`tier`), and the frontend
(`GroundingTag`), and a missing content dependency always lands in
`missing_sections` rather than being silently omitted or fabricated.

### Delivered (Units 1-4)

| Area | State |
|---|---|
| Report + grounding contracts, object storage (Unit 1) | `sm_contracts.report` — `GroundingKind` (`evidence`/`inference`/`prediction`/`synthetic`), `GroundedStatement`, `Report`, `ReportGeneratedPayload`. `sm_common.db.report_models` + migration `0011` (`report`/`report_template`, JSONB body, seeded default template per `ReportKind` via an explicit `CAST(:sections AS jsonb)` — `op.bulk_insert` cannot round-trip a JSONB column online or offline). New `sm_common.objectstore` (ADR-019): `ObjectStore` (async `aioboto3`), `safe_key()` (path-traversal / malicious-filename guard), `ensure_bucket()` (idempotent, default SSE-S3 encryption). |
| `reporting-service` (Unit 2) | `services/reporting-service` (port 8013, HTTP-triggered). Gathers content from `detection-engine` (direct Postgres read), `graph-service`/`mitre-service`/`ai-analyst`/`memory-service` (internal HTTP). `ai-analyst`'s narrative only called for a `detection` subject; a `memory-service` prediction at `confidence==0.0` never surfaces as a finding. A missing dependency's section lands in `missing_sections` -> `partial` (filtered against the report kind's own seeded template sections); only an object-storage failure produces `failed`. `POST /api/v1/reports` + `GET /api/v1/reports/{id}` (presigned download, 5-minute TTL). Produces `report.generated`. |
| Attack storytelling (Unit 3, R33) | `services/ai-analyst` — `NarrativeComposer`: one deterministic `NarrativeBeat` per chain stage (never LLM-touched) + one grounded summary paragraph reusing `IncidentAnalyst.explain`'s citation-and-retry mechanism (cite a beat's `stage`, one repair turn, then a factual template with `degraded=True`). A simulation-sourced chain (`is_synthetic_id`) narrates every beat as `synthetic` with `Narrative.simulated=True`. `GET /api/v1/incidents/{chain_id}/narrative` — "incident" is an attack chain id (no separate `Incident` entity exists yet). ai-analyst's first database (`narrative`, migration `0012`) and first cross-service call (`chains_client.py` to `correlation-engine`). |
| BFF + frontend + close (Unit 4) | `api-gateway` `routes/reports.py`: `POST /api/v1/soc/reports` (`requested_by` always server-derived from the session principal, never from the client body; a `compliance`-kind report additionally requires `lead`/`tenant_admin`, enforced in route code atop `reports:generate`), `GET /api/v1/soc/reports/{id}`, `GET /api/v1/soc/incidents/{chain_id}/narrative` (gated on the existing `detections:read` tier). Migration `0013` widens `permission.code`, seeds/grants `reports:read` to all five roles. `frontend/web/app/(soc)/reports` (builder + session-local library + lookup-by-id with presigned download) and `.../story` (chain narrative view), both via a new shared `GroundingTag` component (`.tier-badge` CSS). |

### Verification performed (local + CI, 2026-09-11/12)

- `ruff check` clean over `packages services tests migrations scripts`;
  `mypy --strict` clean over the full CI static-tree list (grew unit over
  unit as `sm_reporting_service` and ai-analyst's new modules were added).
- **883 unit tests** total by phase close (61 new across the phase: 11
  Unit 1 objectstore/contracts, 27 Unit 2 reporting-service, 13 Unit 3
  narrative, 10 Unit 4 BFF) + `gen_contracts.py --check` (100 JSON Schema
  files, 3 new: `Report`, `Narrative`, `NarrativeBeat`/`ReportDownload`).
- Real infra: `tests/integration/test_objectstore_s3.py` (5, Unit 1, real
  MinIO), `test_reporting_repositories_pg.py` (6, Unit 2),
  `test_narrative_repository_pg.py` (4, Unit 3), `test_migrations_pg.py`
  updated three times (heads `0011`→`0012`→`0013`; 18 permissions after
  `reports:read`). Full `tests/integration` suite green against real
  PostgreSQL/Redis/Neo4j/Kafka/MinIO after every unit.
- Manual end-to-end smoke test through the real docker-compose stack for
  Units 2, 3, and 4: real seed rows via `psql`, real internal JWTs, real
  HTTP through the actual running containers — a real PDF uploaded to
  MinIO and downloaded via its presigned URL, a real narrative call
  through `correlation-engine` over the network (including a
  `sim`-prefixed subject confirming every beat tagged `synthetic`), a
  real report created through the BFF with `requested_by` correctly
  server-derived, and a real 403 for a `compliance` report requested by an
  `analyst`-role user.
- `frontend/web`: `npm run lint` clean, `npm run build` OK (21 routes,
  `/reports` + `/story` new), **62 vitest tests** (6 new page tests + 2
  new `contract.test.ts` fixtures).
- `docker build -f deploy/docker/Dockerfile.app` builds; `sm_reporting_service`
  + `sm_common.objectstore` + `reportlab` + `aioboto3` import in the image;
  non-root uid confirmed.
- **CI green on a clean runner — all five jobs, final run `34641513223`**
  (earlier unit runs `34597754999` / `34631135008` / `34635710315`).
  Unit 4's first push (`34640559225`) failed on Docker Hub denying
  anonymous pulls of the pinned MinIO release tag — reproduced identically
  via a local `docker pull` and one CI rerun (ruling out a transient
  blip), confirmed `quay.io/minio/minio` serves the identical image digest,
  and fixed by repointing both `docker-compose.yml` and CI's "Start MinIO"
  step at the quay.io mirror.

### Pre-output engineering review (Constitution §23)

- **Grounding is real, not cosmetic.** `GroundedStatement.tier` is a
  required field wherever a report carries a claim (evidence/findings/
  recommendations), and `NarrativeBeat.tier` likewise for every beat — a
  contract-level test (`contract.test.ts`) asserts a fixture cannot omit
  it. The only LLM-authored text in either surface (`Narrative.summary`)
  goes through the same citation-and-retry grounding `IncidentAnalyst.
  explain` already uses, never a fresh ungrounded generation path.
- **Never fabricate a missing section.** A reporting-service content
  dependency that is unreachable or empty lands its section name in
  `missing_sections` and the report's `status` becomes `partial` — never
  silently dropped, never backfilled with invented content. Verified by
  the real end-to-end smoke test (a report generated with graph-service/
  memory-service unreachable came back `partial` with both listed).
- **Authorization + audit, including a role gate beyond the base
  permission.** Every reports/narrative BFF route is behind
  `require_permission` (deny-by-default, audited on denial); a
  `compliance`-kind report additionally requires `lead`/`tenant_admin` in
  route code — a real end-to-end 403 was observed for an `analyst`-role
  user, not just a unit-test assertion.
- **Never trust a client-supplied identity field.** `CreateReportRequest`
  has no `requested_by` field at all (`extra="forbid"` rejects one); the
  BFF always derives it from the verified session principal. A test
  proves a client-supplied `requested_by` in the request body causes a
  422, not silent acceptance.
- **Path-traversal / malicious-filename guard on every object key.**
  `safe_key()` is the only way to build an S3 key anywhere in the build —
  rejects `.`/`..`/path separators/anything outside a conservative
  allow-list, tested before ever reaching MinIO.
- **Simulation is tagged at the contract level, not just a UI badge.** A
  simulation-sourced chain's narrative carries `simulated=True` and every
  beat's `tier=synthetic` in the data itself — a consumer of the raw API
  response (not just the rendered page) can tell synthetic from real.
- **External-infrastructure failure diagnosed, not worked around
  blindly.** The Unit-4 CI failure was root-caused as a genuine Docker Hub
  registry change (confirmed via independent reproduction, not assumed)
  before any fix was applied — the fix points at the same publisher's own
  mirror with the identical image digest, not an unrelated substitute.

### Deferred (deliberately)

- **A server-side report list endpoint.** `frontend/web/app/(soc)/reports`
  keeps a session-local library only; there is no `GET /api/v1/soc/reports`
  list route. Look-up-by-id is the only retrieval path for a report a
  user didn't just create in this session (R22's stated deviation).
- **A cinematic/animated replay view.** `.../story` renders the
  deterministic beats + grounded summary as a static list, not an
  animated timeline — R33's "storytelling" is satisfied by the grounded
  narrative content, not a presentation-layer animation.
- **A separate `Incident` entity.** "Incident" in the narrative route
  remains an attack chain id; `docs/CONTRACTS.md` §3 still lists a
  distinct `Incident` entity as PLANNED, not introduced this phase.
- **Narrative beats for non-detection subjects' LLM explanation.**
  `ai-analyst`'s grounded `/explain` has no host/ip/domain/identity
  variant in its contract; reporting-service's narrative section is
  correspondingly detection-subject-only, unchanged from Unit 2's
  documented scope.

### Exit criteria status

| Criterion | Status |
|---|---|
| Report generation: incident reports, executive summaries, compliance reports, threat briefings | ✅ `ReportKind` (`incident`/`executive`/`compliance`/`threat_briefing`), one seeded template each |
| Every report distinguishes evidence / inference / prediction / synthetic data | ✅ `GroundingKind` threaded through every `GroundedStatement` and `NarrativeBeat.tier` |
| Never fabricate a missing section | ✅ `missing_sections` -> `partial`, real-smoke-tested |
| Attack storytelling / narrative generation (R33) | ✅ deterministic beats + one grounded, citation-checked summary; `degraded` fallback never invents a stage |
| Secure export (path traversal, malicious filenames, etc.) | ✅ `safe_key()` — path-traversal guard tested before touching the backend; presigned, time-limited download URLs, never a public object |
| Role-gated report kinds (compliance) | ✅ `lead`/`tenant_admin` gate in route code atop `reports:generate`, real end-to-end 403 verified |
| Tests: grounding-tier assertions, missing-section behavior, role gate, presigned URL round trip, path-traversal rejection | ✅ all covered — unit + real-Postgres + real-MinIO + manual end-to-end |
| **CI green on a clean runner** | ✅ **all five jobs — final run `34641513223`** (unit runs `34597754999` / `34631135008` / `34635710315`) |

## Phase 13 exit report

**State: COMPLETE / CI-VERIFIED (all five jobs, final run
[`34591054542`](https://github.com/gaurav685/sentinelmesh/actions/runs/34591054542)).**
Unit 1 `fcdcdd7`, Unit 2 `2b802aa`, Unit 3 `50c3cbc`, Unit 4 `0893662`.
Unit-level CI runs: 1 = `34582276848`, 2 = `34586331308`, 3 = `34588573722`,
4 = `34591054542` (all five jobs each time).

**Three distinct stores, one graph database (ADR-011).** The operational
attack graph and the persistent knowledge graph both stay in Neo4j
(`graph-service`) — unchanged this phase. **Threat memory** is new:
Postgres + pgvector, owned by `memory-service`, analytical/vector state that
duplicates neither the graph nor the detection/chain tables. **Every
prediction is a deterministic heuristic, never a trained model, and says
so** — `sm_ml.predict`'s `MODEL_VERSION = "heuristic-v1"` is not decoration;
there is no dataset, no training run, and `confidence=0.0` with a stated
reason is the honest answer whenever the input cannot support one.

### Delivered (Units 1-4)

| Area | State |
|---|---|
| Threat-memory core (Unit 1) | `sm_ml.memory.technique_feature_vector` (deterministic, L2-normalized, hashed-bag-of-techniques — not a trained embedding) + `cosine_similarity` (the Python exact-match fallback). `sm_common.db.memory_models` — `ThreatMemoryRow` / `CampaignRow` / `AdversaryFingerprintRow`, each a `pgvector` `vector(32)` column + `hnsw`/`vector_cosine_ops` index (migration `0009`, `CREATE EXTENSION vector`). `sm_contracts.memory` — the raw feature vector is never returned over the API, only a similarity score. Postgres image swapped to `pgvector/pgvector:pg16` (ADR-006). |
| memory-service ingestion + campaigns + retention (Unit 2) | `services/memory-service` (port 8012) consumes `attack_chains` (group `memory`), fetches the full chain from `correlation-engine` (`ChainsClient` — the topic event has no technique data), upserts a `ThreatMemory` pattern, matches-or-starts a `Campaign` (pgvector cosine similarity, exact-fallback on a DB error), upserts an `AdversaryFingerprint`, produces `campaign.updates`. `POST /api/v1/memory/similar` + read routes. `RetentionSweeper` — the deletion lifecycle: `active -> dormant -> closed` on inactivity, deleted past `SM_MEMORY_RETENTION_DAYS`. |
| Prediction interfaces (Unit 3) | `sm_ml.predict` — `predict_attack_progression`, `predict_next_action`, `predict_lateral_movement`, `predict_threat_trajectory`, each a documented deterministic rule. `sm_contracts.api.prediction.Prediction` (`prediction`, `confidence`, `evidence`, `features`, `model_version`, `generated_at`; `subject_type` is `None` for the campaign-level `threat_trajectory`). `memory-service` `POST /api/v1/predict/{attack-progression,next-action,lateral-movement,threat-trajectory}`. |
| BFF + frontend + close (Unit 4) | `api-gateway` `routes/memory.py` — full proxy for threat-memory retrieval + predictions under `/api/v1/soc/{memory,predict}/...`, `require_permission(memory:read)` (new permission, migration `0010`, granted to every role including `read_only` — this is read-only analytical information, unlike the operator-action permissions in Phase 12). `frontend/web/app/(soc)/memory` — campaigns (+ predict trajectory), fingerprint lookup (+ predict lateral movement), similarity search, chain predictions (progression / next action) — every prediction rendered with its confidence, evidence, and model version, never a bare verdict. |

### Verification performed (local, 2026-09-11)

- `ruff check` clean over `packages services tests migrations scripts`;
  `mypy --strict` over all 18 static trees (364 files) clean.
- **822 unit tests** total (60 new across the phase: 11 feature-vector, 16
  memory-service Unit 2, 22 prediction Unit 3, 10 BFF Unit 4 — plus the
  memory-model tests already counted in the 774→790→812→822 progression)
  + `gen_contracts.py --check` (92 JSON Schema files).
- Real infra: `tests/integration/test_memory_models_pg.py` (6, Unit 1),
  `test_memory_repository_pg.py` (6, Unit 2 — caught a real
  `autoflush=False` bug in the retention sweep), `test_migrations_pg.py`
  updated three times (heads `0009` then `0010`; 17 permissions,
  `platform_operator` holds all 17). Full `tests/integration` suite green
  against real PostgreSQL 16 (`pgvector/pgvector:pg16`) + Redis + Neo4j 5
  after every unit.
- `frontend/web`: `npm run lint` clean, `npm run build` OK (18 routes,
  `/memory` new), **56 vitest tests** (3 new memory-page + 2 new
  `contract.test.ts` fixtures).
- `docker build -f deploy/docker/Dockerfile.app` builds; `sm_memory_service`
  + `pgvector.sqlalchemy` import in the image; non-root uid `10001`
  confirmed.
- **CI green on a clean runner — all five jobs, final run `34591054542`**
  (earlier unit runs `34582276848` / `34586331308` / `34588573722`).

### Pre-output engineering review (Constitution §23)

- **Never present a prediction as fact (the phase's explicit instruction).**
  Every `Prediction` carries `confidence`, `evidence`, `model_version`, and
  `generated_at` as required fields — there is no code path that returns a
  bare string verdict. `model_version = "heuristic-v1"` names a rule set,
  never a training run; nothing in `sm_ml.predict` imports a ML framework or
  loads an artifact. When an input cannot support a prediction (an empty
  candidate set, an unmapped stage, no shared technique), every function
  returns `confidence=0.0` with a human-readable reason in `prediction`
  rather than a low-confidence guess — a unit test asserts this for each of
  the four functions.
- **Three distinct stores, never duplicated (the memory-architecture
  instruction).** ADR-011's split is followed, not just cited: `graph-service`
  owns the operational + knowledge graph (Neo4j, unchanged this phase);
  `memory-service` owns threat memory (Postgres + pgvector) — a behavioral
  pattern, a campaign, and a fingerprint are three distinct row kinds, never
  one shared "memory" table; `detection-engine` / `correlation-engine` keep
  owning the detection/chain tables memory-service only reads from (via
  `correlation-engine`'s API, never a direct table read — no cross-service
  Postgres access anywhere in this build). R37's fingerprint similarity
  introduces no fourth store — `campaign_ids` on the fingerprint row is the
  only "similarity" linkage, exactly as ADR-011 specifies.
- **Storage / indexing / retention / retrieval / provenance / tenant
  isolation / deletion lifecycle — all defined, not just storage.**
  Indexing: `hnsw`/`vector_cosine_ops` per vector column. Retention +
  deletion: `RetentionSweeper` ages `active -> dormant -> closed` then
  deletes past `SM_MEMORY_RETENTION_DAYS` — real-Postgres-tested. Retrieval:
  `POST /api/v1/memory/similar` with a documented fallback path. Provenance:
  `ThreatMemory.source` is always `"attack_chain:<uuid>"` — traceable back to
  a real chain, never fabricated. Tenant isolation: every repository query
  filters `tenant_id = :tenant` from the verified internal token; a
  real-Postgres test proves a second tenant sees nothing.
- **Similarity is real, and its limits are visible.** `SimilarityMatch.
  exact_fallback` tells a caller whether pgvector or the bounded Python scan
  answered — never silently one or the other. The raw feature vector is
  never part of any response (contracts and a route test both enforce this).
- **Authorization + audit.** Every new BFF route is behind
  `require_permission(PermissionCode.memory_read)` (deny-by-default, metered
  + audited on denial); a test asserts `globex_admin` (lacking the
  permission) gets 403. Unlike Phase 12's operator-action permissions,
  `memory:read` is granted to `read_only` too — this is passive observation,
  not an action.
- **No fabricated metrics, no fabricated attack activity, no fabricated
  similarity score.** `technique_feature_vector` and `cosine_similarity` are
  named and documented as a deterministic rule, not an embedding model,
  everywhere they appear (docstrings, `docs/CONTRACTS.md`, this report).
  `docs/REQUIREMENTS_TRACEABILITY.md` R15 is marked IMPLEMENTED **as
  heuristics**, with the deviation from a trained sequence model stated
  plainly rather than rounded up.

### Deferred (deliberately)

- **A trained predictive model.** R15's original shape
  (`{predicted_action, probability, horizon, confidence}` from a sequence
  model, MLflow-tracked) remains future work — no dataset/training run has
  produced one. The four heuristic interfaces this phase delivers are what
  the phase prompt actually asked for ("implement prediction interfaces"),
  and they are real, tested, and honest about not being ML.
- **A live graph-based lateral-movement predictor.** `predict_lateral_movement`
  uses fingerprint technique-overlap, not a Neo4j traversal from the
  operational graph — self-contained within `memory-service`'s own data,
  deliberately not a new cross-service graph query this phase.
- **Wiring "similar past campaigns" into an AI-analyst explanation.** The
  retrieval + prediction API is real; nothing in `ai-analyst` or an
  agent automatically calls it yet (R37's stated deviation).
- **A `campaign_similarity` table.** R37's spec named one; ADR-011 already
  said this would introduce no new store, and the build holds to that —
  `AdversaryFingerprintRow.campaign_ids` is the only similarity linkage.

### Exit criteria status

| Criterion | Status |
|---|---|
| Threat memory: behavioral pattern persistence, campaign evolution, attacker fingerprinting, similarity analysis | ✅ `ThreatMemoryRow` / `CampaignRow` / `AdversaryFingerprintRow`, pgvector similarity + exact fallback |
| Memory architecture: clearly separate Knowledge Graph / Threat Memory / Operational Incident State / AI Context, no unnecessary duplication | ✅ ADR-011's three-store split, held to; no shared "memory" table, no cross-service table reads |
| Storage / indexing / retention / retrieval / provenance / tenant isolation / deletion lifecycle | ✅ all defined and real-Postgres-tested |
| Prediction interfaces: attack progression, lateral movement, next attacker action, threat trajectory | ✅ all four, `sm_ml.predict` |
| Every prediction: prediction + confidence + evidence/features + model version + timestamp | ✅ `Prediction` contract, enforced by the schema itself |
| Never present a prediction as fact | ✅ `confidence=0.0` + a stated reason when underdetermined; no bare verdict anywhere |
| Tests: memory write/read, retention, tenant isolation, similarity, prediction schema, model failure, stale memory, evidence grounding | ✅ all covered — real-Postgres tests for retention/tenant-isolation/similarity, unit tests for prediction schema + "model failure" (underdetermined-input) paths |
| **CI green on a clean runner** | ✅ **all five jobs — final run `34591054542`** (unit runs `34582276848` / `34586331308` / `34588573722`) |

## Phase 12 exit report

**State: COMPLETE / CI-VERIFIED (all five jobs, final run
[`34576850936`](https://github.com/gaurav685/sentinelmesh/actions/runs/34576850936)).**
Unit 1 `dd175ad`, Unit 2 `6506b05`, Unit 3 `c976438` (+ CI fix `59d5991`),
Unit 4 `88d37d2`. Unit-level CI runs: 1 = `34449930913`, 2 = `34569040279`,
3 = `34572530014`, 4 = `34576850936` (all five jobs each time).

**Simulation stays isolated. There is no code path from a scenario or a decoy
to a real system.** A scenario's target must be a synthetic (`sim-`-prefixed)
id present in a synthetic environment generated from the request's own seed —
`ScenarioIsolationError` refuses anything else before a single event is
produced. `feed_pipeline: true` only ever produces onto the one `telemetry.raw`
topic every other producer already writes to, with `source.type = "simulation"`
on every envelope — there is no other topic, queue, or network call a scenario
can reach. A decoy's `network_boundary` can only be `isolated` or
`dmz-isolated` — `'production'` is not a legal value at the API schema layer
**or** the database `CHECK` constraint, so it cannot be recorded even if a
caller bypasses the API. A decoy carries no credential field at all.
Interaction capture is one-way (there is no endpoint that pushes anything
from a decoy back out). Teardown is idempotent and the interaction history
survives it for audit.

### Delivered (Units 1-4)

| Area | State |
|---|---|
| Digital twin (Unit 1) | `sm_ml.twin` — `TwinModel` (`TwinAsset` / `TwinRelation` / `TwinWeakness`, `build_twin` validates + freezes + sorts, deterministic stdlib). `attack_paths` (bounded simple paths, feasibility-ordered), `blast_radius` → `BlastRadiusReport` (reached set, per-hop, critical-reached, criticality-weighted score, amplifying weaknesses), `stress_test` + `DefensiveControl` → which paths a control set breaks + residual risk + most-valuable control. |
| Synthetic scenario engine (Unit 2) | `sm_ml.scenario` — `build_synthetic_env(seed)` (deterministic, every id `sim-`-prefixed), `ScenarioSpec` (apt / ransomware / insider / brute_force, Pydantic frozen + `extra=forbid`), `validate_spec` (`ScenarioIsolationError` unless every target is synthetic and present), `run_scenario` (seeded-RNG deterministic ordered `SimEvent`s, each `simulated=True` + `scenario_id`), `replay_run` (deterministic read-only slice). |
| Simulation service + deception registry (Unit 3) | `services/simulation-service` (port 8011): `POST /api/v1/sim/scenarios/run` (isolation-refused → 422, `feed_pipeline` with no bus → 422); `pipeline.py` maps `SimEvent` → the closest real telemetry payload and produces it with `source.type = "simulation"`. Deception: `POST/GET/DELETE /api/v1/deception/decoys...`, `DecoyRepository` over Postgres `decoy` / `decoy_interaction` (migration `0007`); idempotent teardown; a torn-down decoy captures nothing further. `sm_contracts.api.simulation` (`RunScenarioRequest` / `ScenarioRunResult` / `RegisterDecoyRequest` / `Decoy` / `DecoyInteractionIn` / `DecoyInteraction`). |
| Twin surfaced + BFF + frontend (Unit 4) | `sm_ml.twin.twin_from_synthetic_env(env) -> TwinModel` — a deterministic twin read off the *same* synthetic environment a scenario runs against (a fixed role-dependency graph: `web → app → db/file`, `workstation → dc`, `dc trusts` every other host; `dc`/`db` get seeded weaknesses) — no second, independently-maintained asset inventory to drift from it. `GET /api/v1/sim/twin?seed=` + `POST /api/v1/sim/twin/blast-radius` on `simulation-service`. New permissions `simulation:run` / `deception:manage` (migration `0008`: widens the `permission.code` CHECK, seeds both codes, grants to `platform_operator` / `tenant_admin` / `lead` / `analyst` — deliberately not `read_only`). `api-gateway` `routes/simulation.py` — full BFF proxy (`/api/v1/soc/simulation/{run,twin,blast-radius}`, `/api/v1/soc/deception/decoys...`), every route `require_permission` + CSRF on writes, tenant from the session `Principal`; `InternalServiceClient._request` now re-raises a downstream `422` as `ValidationFailed` (previously flattened into a misleading `DependencyUnavailable` 503 — an isolation refusal is not an outage). `frontend/web/app/(soc)/simulation` (run form, twin asset/relation/weakness tables, per-asset blast-radius view) and `.../deception` (register / list / teardown / interactions), both badged "SIMULATION"; nav entries gated on the new permissions. |

### Verification performed (local, 2026-09-11)

- `ruff check` clean over `packages services tests migrations scripts`;
  `mypy --strict` over all 17 static trees CI checks (339 files) clean.
- **763 unit tests** (24 new this unit: 7 `sm_ml.twin` synthetic-twin tests, 5
  `simulation-service` twin-route tests, 12 `api-gateway` simulation/deception
  BFF tests) + `gen_contracts.py --check` (87 JSON Schema files, up from 84).
- Real infra: `tests/integration` full suite green against real
  PostgreSQL 16 + Redis + Neo4j 5 (`SM_REQUIRE_INTEGRATION=1` — a skip fails
  the run); `test_migrations_pg.py` updated for the new head (`0008`) and
  permission/grant counts (16 permissions; `platform_operator` holds all 16).
- `frontend/web`: `npm run lint` clean, `npm run build` OK (17 routes,
  `/simulation` + `/deception` new), **51 vitest tests** (9 new: 2 simulation
  page, 5 deception page, 3 `contract.test.ts` fixtures for
  `ScenarioRunResult` / `TwinSnapshot` + `BlastRadiusResult` / `Decoy`).
- `docker build -f deploy/docker/Dockerfile.app` builds; `sm_simulation_service`
  (and every other service module) imports in the image; non-root uid `10001`
  confirmed; the production fail-fast guards still refuse an unsafe config.
- **CI green on a clean runner — all five jobs, final run `34576850936`**
  (earlier unit runs `34449930913` / `34569040279` / `34572530014`).

### Pre-output engineering review (Constitution §23)

- **Never build uncontrolled offensive tooling; never let simulation attack
  arbitrary external systems (the phase's SAFETY clause).** A scenario's
  `target_host` / `target_identity` must be `is_synthetic_id` **and** present
  in the seed-derived `SyntheticEnvironment`, checked by `validate_spec`
  before `run_scenario` produces a single event — a real-looking id
  (`web01`) or an id from a different seed's environment is refused (422).
  There is no HTTP client, socket, or subprocess anywhere in
  `sm_ml.scenario` or `services/simulation-service`'s scenario path; the only
  network egress `feed_pipeline` performs is a `Kafka` produce onto
  `telemetry.raw`, the same topic `ingestion-gateway` already writes to.
- **Deception isolation, explicit boundaries, limited credentials, capture,
  audit, teardown.** `NetworkBoundary = Literal["isolated", "dmz-isolated"]`
  — `'production'` is absent from the type, so a request for it is a 422
  before any handler runs; the same allow-list is a Postgres `CHECK`
  (`ck_decoy_network_boundary`), verified against real Postgres in
  `tests/integration/test_simulation_pg.py::test_network_boundary_check_
  rejects_production_at_the_database_level` (a raw `INSERT ... 'production'`
  raises `IntegrityError`). `Decoy` / `RegisterDecoyRequest` have no
  credential-shaped field at all. `DecoyInteractionIn` captures
  attacker-supplied `source` / `technique_hint` / `detail` for **display
  only** — never parsed as anything executable, never fed back anywhere.
  `DELETE .../decoys/{id}` (teardown) is idempotent and a torn-down decoy's
  `record_interaction` returns `None` (404 at the API), so it captures
  nothing further; interaction history is retained (never deleted) for audit.
- **Twin runs cannot affect production detection or emit a response action.**
  `twin_from_synthetic_env` only ever reads a `SyntheticEnvironment` — it has
  no code path to Neo4j, Postgres, or any other service; `blast_radius` /
  `attack_paths` are pure functions over that in-memory model. Nothing in
  Phase 12 calls `sm_ai.agents.action_gate` or produces a `response.action` —
  there is no path from a twin or scenario result to an autonomous action.
- **Authorization + audit.** Every new BFF route is behind
  `require_permission(PermissionCode.simulation_run |
  PermissionCode.deception_manage)` (deny-by-default, metered + audited on
  denial) plus CSRF double-submit on every write; a test asserts
  `globex_admin` (neither permission) gets 403 on both surfaces. `simulation:run`
  and `deception:manage` are new, closed-vocabulary permission codes (a
  migration widens the `permission.code` CHECK — the same pattern `0002`
  established, never a free-text column) and are not granted to `read_only`.
- **A downstream validation failure is not disguised as an outage.**
  `InternalServiceClient._request` previously flattened every non-2xx,
  non-404 status (including a legitimate 422 isolation refusal) into
  `DependencyUnavailable` (503) — technically safe (the UI never fabricates
  a result) but misleading (a 503 reads as "the service is down", not "your
  request was invalid"). Fixed to re-raise a `422` as `ValidationFailed`,
  carrying the dependency's own message; a test
  (`test_run_scenario_isolation_refusal_is_422_not_503`) asserts the BFF now
  returns 422, not 503, for an isolation refusal.
- **No fabricated metrics, no fabricated attack activity.** `TwinModel`'s
  criticality / weight / severity values are fixed constants attached to a
  synthetic role graph, never presented as a measured or trained figure.
  Every scenario response has `synthetic: true`; every emitted event has
  `simulated: true`; both frontend pages carry a visible "SIMULATION" badge.
  `docs/REQUIREMENTS_TRACEABILITY.md` R26 is marked **FOUNDATION
  IMPLEMENTED**, not complete — no demo-tenant or guided-walkthrough layer
  was built, and the doc says so rather than rounding up.
- **The twin has no separate, independently-maintained asset inventory to
  drift from reality.** `twin_from_synthetic_env` is a pure read of the same
  `SyntheticEnvironment` object a scenario run is validated against — there
  is exactly one source of truth for "what synthetic entities exist," not two
  that could silently disagree.

### Deferred (deliberately)

- **A twin over anything but the synthetic environment.** There is no
  real-asset digital twin in this build — R35's "environment representation"
  is the synthetic estate only; a production asset inventory feeding a twin
  is future work.
- **Persisting a scenario run.** A run's events are returned in the response
  and, optionally, streamed into the telemetry pipeline; nothing about the
  run itself (its spec, its id, when it ran) is written to Postgres. Decoys
  and their interactions *are* persisted — this gap is scenario-runs only.
- **`stress_test` / `DefensiveControl` are not exposed through any API yet.**
  `sm_ml.twin.stress_test` exists and is unit-tested (Unit 1) but
  `simulation-service` only surfaces `blast_radius` and `attack_paths`
  indirectly (via the reached-set in the blast-radius response); a
  dedicated "what would blocking X break" endpoint is future work.
- **R26's demo-tenant / guided-walkthrough layer.** The engine it would run
  on exists (R17); the demo-specific UI and tenant isolation do not.
- **Adversary profiling (R16's optional clustering).** Never in scope for
  this build; interaction capture is the full extent of "profiling" here.
- **A k8s network-policy isolation test.** There is no k8s deployment yet;
  isolation is enforced by the data model (schema + DB CHECK), not a network
  boundary — stated as a limitation, not hidden.

### Exit criteria status

| Criterion | Status |
|---|---|
| Synthetic attack scenarios: APT / ransomware / insider-threat / brute-force | ✅ four deterministic templates, `sm_ml.scenario` |
| Attack replay | ✅ `replay_run` (deterministic read-only slice) |
| Deception / honeypot architecture: isolation, explicit boundaries, limited credentials, capture, audit, teardown | ✅ schema + DB-CHECK boundary allow-list, no credential field, one-way capture, idempotent teardown, retained history |
| Never uncontrolled offensive tooling; never attack arbitrary external systems | ✅ synthetic-id-only targets, `ScenarioIsolationError`, no network egress beyond one Kafka topic |
| Never connect deception infra to production without explicit controls | ✅ `'production'` is not a legal `network_boundary` value at schema **or** DB level |
| Digital twin: assets, relationships, dependencies, vulnerabilities/misconfigs, attack paths, blast radius | ✅ `sm_ml.twin` + `twin_from_synthetic_env`; scenario execution runs against the model, never real systems |
| Defensive stress testing | ✅ `stress_test` + `DefensiveControl` (library-level; no dedicated API yet) |
| Tests: deterministic scenarios, isolation, replay, blast-radius calculation, deception event capture, teardown, authorization | ✅ all covered, incl. real-Postgres CHECK-constraint verification |
| **CI green on a clean runner** | ✅ **all five jobs — final run `34576850936`** (unit runs `34449930913` / `34569040279` / `34572530014`) |

## Phase 11 exit report

**State: COMPLETE / CI-VERIFIED (all five jobs, final run
[`34448406595`](https://github.com/gaurav685/sentinelmesh/actions/runs/34448406595)).**
Units 1-3 commits `a9e4293` / `9cb52e1` / `9e07387`.
Earlier unit runs `34446018571` / `34447606633`.

**`raw LLM output → executed Cypher` is impossible. The pipeline is
`natural language → QueryPlan (closed schema) → validation → authorization →
one of a fixed set of parameterized Cypher templates → result → grounded
explanation`. The LLM only ever produces a `QueryPlan` (parsed into the Pydantic
model — never used as a query) or `{"unsupported": true}`. `graph-service`
interpolates only an allow-listed node label, allow-listed relationship-type
names, and a clamped integer depth; every entity value is a `$`-parameter; the
tenant is `$tenant` from the verified token and `QueryPlan` has no tenant field.
No live LLM has been called (deterministic adapter only, ADR-014) — with no key
an NL hunt is `unsupported`, never guessed.**

### Delivered (Units 1-3)

| Area | State |
|---|---|
| Contracts + compiler (Unit 1) | `sm_contracts.api.hunt` — `QueryPlan` (`HuntIntent` ∈ {find_entity, list_related, path_between, detections_for, chains_for, indicator_sightings, technique_usage}, typed `EntitySelector`s, `rel_types` allow-list, `QueryLimits`), `NlHuntRequest`, `PlanResponse`, `HuntResult`. `graph-service` `hunt.py` — `validate_plan` (capability-set enforcement: selector count/type per intent, `rel_types` ⊆ `GRAPH_REL_TYPES`, `rel_types` only on `list_related`), `compile_plan` (one constant parameterized Cypher per intent; label/reltype/int-depth are the only interpolations, all allow-listed), `HuntRunner`. `POST /api/v1/graph/hunt` (internal JWT; a plan outside the set → 422). `SM_HUNT_MAX_ROWS` (200) / `SM_HUNT_MAX_DEPTH` (3), applied on top of the plan's limits. `HuntResult.cypher_fingerprint` (sha256 of the template) proves which fixed query ran. |
| NL + orchestration + history (Unit 2) | `ai-analyst` `HuntPlanner` (`POST /api/v1/hunt/plan`) — the LLM's JSON is parsed into `QueryPlan`; non-JSON / invalid intent / no LLM → `PlanResponse(supported=false)`. `explain_hunt` + `POST /api/v1/hunt/explain` — grounded, cites the plan; deterministic baseline without an LLM. `api-gateway` `POST /api/v1/soc/hunt` (`require_permission(hunt:query)` + CSRF, tenant from the session `Principal`) — `body.plan` → run directly; `body.query` → `/hunt/plan` (unsupported → `SocHuntResponse(supported=false)`, **not executed**) → `/graph/hunt` → `/hunt/explain`. The NL text is never sent to `graph-service`. `hunt_query` history (`sm_common.db.HuntQueryRow` + migration `0006`, append-only, tenant-scoped; `SqlSocRepository.record_hunt`). `SocHuntRequest` / `SocHuntResponse` / `HuntExplainRequest`. |
| Frontend hunt panel (Unit 3) | `frontend/web/app/(soc)/hunt` — an "Ask" NL mode (`{query}`) and a "Quick query" structured form (`{plan}`, no LLM), both showing the **compiled `QueryPlan`** in a `<details>` for transparency, the grounded explanation, a rows table, and a "Pivot" action (runs `list_related` on a result row's entity). Nav entry gated on `hunt:query`. `api.hunt(body, csrfToken)` typed helper; `contract.test.ts` fixture check for `SocHuntResponse`. |

### Verification performed (local, 2026-09-10)

- `ruff check` clean; `mypy --strict` over all 17 src trees (308 files) clean;
  **694 unit tests** (`graph-service` hunt: 22; `ai-analyst` hunt: 10;
  `api-gateway` `/soc/hunt`: 6) + `gen_contracts.py --check`.
- `frontend/web`: `npm run lint` clean, `npm run build` OK (15 routes),
  **41 vitest tests** (3 new hunt-panel: NL result + shows the plan, unsupported
  reason shown and not pretended-run, quick structured plan).
- Real infra: `tests/integration/test_migrations_pg.py` (0006 up + down against
  real PostgreSQL 16); `tests/integration/test_hunt_neo4j.py` against real
  Neo4j 5 — a hunt runs, is tenant-scoped, cross-tenant isolation holds (tenant B
  cannot see tenant A's `web01`), a hallucinated entity → empty result.
- `docker build -f deploy/docker/Dockerfile.app` builds; `sm_ai_analyst.hunt` +
  `sm_common.db.HuntQueryRow` import in the image.
- **CI green on a clean runner — all five jobs, final run `34448406595`**
  (earlier unit runs `34446018571` / `34447606633`).

### Pre-output engineering review (Constitution §23)

- **Never `raw LLM output → executed Cypher` (the phase's CRITICAL SECURITY
  clause).** The LLM's only output path is `QueryPlan.model_validate(json)` — a
  closed Pydantic schema. There is no code path that takes model text and runs
  it. A test asserts the planner can only ever yield a `QueryPlan` or
  `unsupported` even for a hostile NL string that makes the model emit Cypher.
- **Only a predefined capability set.** `HuntIntent` is a 7-value `Literal`;
  `validate_plan` rejects a wrong selector count/type per intent, an unknown
  relationship type, and `rel_types` on the wrong intent. `compile_plan` has one
  constant template string per intent — there is no template built from caller
  input.
- **Block writes / destructive / schema-mod queries.** Every template is
  MATCH/WHERE/RETURN/LIMIT only; a unit test greps each compiled query for
  `CREATE|MERGE|DELETE|SET|REMOVE|DROP|CALL` and asserts none. `Graph.run_read`
  is used, not `run_write`.
- **Block cross-tenant access.** `QueryPlan` has **no tenant field** (a test
  asserts `"tenant" not in QueryPlan.model_fields`). The tenant is `$tenant` from
  the verified internal token at every layer; the api-gateway route takes it from
  the session `Principal`, never the body (a stray `tenant_id` in the body → 422).
  Real-Neo4j test: tenant B's hunt for the same natural key returns 0 rows.
- **Block unrestricted traversal / expensive queries.** `SM_HUNT_MAX_DEPTH` (3)
  and `SM_HUNT_MAX_ROWS` (200) are applied on top of the `QueryPlan`'s own
  `QueryLimits` (≤ 4 / ≤ 500) — `compile_plan` clamps `min(plan, server)`. A test
  sets the plan to 4/500 and asserts the compiled query is `*1..3` and `cap=200`.
- **Block data-exfiltration patterns.** `path_between` returns node ids +
  properties along one shortest path (capped at length 3); the other intents
  return a capped distinct node set. `_`-prefixed props and `uid` are stripped.
  There is no intent that dumps a whole label or runs an unbounded scan.
- **Injection.** A Cypher-injection string in a selector value
  (`web01' }) DETACH DELETE (n) //`) is bound as `$v0` and never appears in the
  query text (unit test). An injection string in the NL question can at most make
  the planner return `unsupported`.
- **Authorization + audit.** `/api/v1/soc/hunt` is `require_permission(hunt:query)`
  (deny-by-default, metered + audited) + CSRF double-submit; `globex_admin` (no
  `hunt:query`) → 403. Every hunt — supported or not — is written to `hunt_query`
  (tenant, principal email, mode, NL text, resolved intent, row_count,
  fingerprint; never the rows).
- **Hallucinated entities.** A `find_entity` for a non-existent key is an honest
  empty `HuntResult` (row_count 0), not an error and not a fabricated node
  (real-Neo4j test).
- **The plan is shown to the analyst.** The frontend renders the compiled
  `QueryPlan` JSON so the operator sees exactly what structured query ran.

### Deferred (deliberately)

- **A live LLM provider.** NL planning needs the LLM; with no credentials
  (ADR-014) an NL hunt is `unsupported`. The deterministic adapter is the only
  tested path; the "Quick query" structured mode needs no LLM.
- **Postgres/Neo4j full-text search, a `.../search` endpoint, saved queries.**
  Entity lookup is by natural key (`find_entity`).
- **A dedicated Neo4j read-only role.** The read-only templates + `run_read` are
  the guarantee; a DB-level role is a hardening step for a real deployment.
- **A cross-service integration test of the full `/soc/hunt` chain.** It needs
  api-gateway + ai-analyst + graph-service up together; the orchestration is
  covered by fakes, and each hop has its own real-infra test.
- **`time_range` filtering.** The contract field exists; no template uses it yet.

### Exit criteria status

| Criterion | Status |
|---|---|
| IOC hunting / entity search / graph pivots / advanced graph queries | ✅ 7 intents + the frontend "Pivot" action |
| natural-language threat hunting; NL → intent → structured plan → validation → authorization → parameterized Cypher → result → explanation | ✅ the full pipeline; NL needs an LLM (deferred), structured mode does not |
| never `raw LLM output → direct Cypher execution` | ✅ the LLM only ever produces a `QueryPlan`; asserted by tests |
| only a predefined query-capability set | ✅ 7-value `HuntIntent` `Literal` + `validate_plan` |
| block writes / destructive / schema-mod / cross-tenant / unrestricted traversal / exfiltration | ✅ read-only templates, no tenant field, dual depth/row caps, greps + real-Neo4j tests |
| query validation / authorization | ✅ `validate_plan` → 422; `require_permission(hunt:query)` + CSRF |
| result explanation | ✅ `/hunt/explain` grounded, cites the plan; deterministic baseline |
| tests: injection / unauthorized / cross-tenant / expensive / malformed NL / hallucinated entities / plan-validation / parameterization | ✅ all covered |
| **CI green on a clean runner** | ✅ **all five jobs — final run `34448406595`** (unit runs `34446018571` / `34447606633`) |

## Phase 10 exit report

**State: COMPLETE / CI-VERIFIED (all five jobs, final run
[`34432159191`](https://github.com/gaurav685/sentinelmesh/actions/runs/34432159191)).**
Units 1-4 commits `90cc856` / `5b06de9` / `5f14fb3` / `908148b`.
Earlier unit runs `34429226626` / `34429715242` / `34430968254`.

**The LLM is treated as untrusted throughout. It never gains a privilege it was
not already granted: every tool call goes through a deny-by-default
`ToolRegistry`; an unauthorised or unknown tool the model asks for is refused;
the analyst and the agents hold no standing permissions; the response agent
*proposes* and `action_gate` never returns `allowed` under the shipped config.
No live LLM provider has been called — `HttpLlmBoundary` is written to the
Anthropic Messages shape but is inert without an API key, and no credentials
exist in this project (ADR-014). With no key the AI layer degrades to
deterministic templates / `status=failed`, never a fabricated narrative.**

### Delivered (Units 1-4)

| Area | State |
|---|---|
| `sm_ai` boundary (Unit 1) | Provider-neutral `LlmRequest` / `LlmResponse` / `ToolSpec` / `ToolCall`; `LlmProvider`; `DeterministicAdapter` (network-free, reproducible, `is_live=False` — the default and every test's provider); `HttpLlmBoundary` (inert without a key; never executed live). `LlmClient` — per-call prompt-token ceiling **before any network I/O**, per-run `RunBudget`, wall-clock timeout, cooperative cancellation, transient-only bounded retry (a `ProviderRefused` is never retried), one `AuditEvent` per attempt (`prompt_sha256` + purpose + usage + outcome, never the raw prompt). Config `SM_LLM_*` / `SM_AGENT_*`. |
| Tools + evidence (Unit 2) | `Tool` / `FunctionTool` (explicit Pydantic `args_model`, optional `required_permission`, input + output validation). `ToolRegistry` — deny-by-default: `specs_for(principal)` advertises only authorised tools; `invoke` re-checks existence -> `has_permission` (**the LLM asking is irrelevant**) -> args -> output, emitting a `ToolInvocationRecord` on every path. `scan_for_injection` + `fence_untrusted` (delimiter-lookalikes neutralised). `EvidenceBuilder` (trusted strings plain, all telemetry/third-party content fenced as data, size cap -> `ContextPoisoningDetected`). `build_grounded_messages` — evidence is only ever a `user` turn. |
| `services/ai-analyst` (Unit 3) | HTTP-only, port 8010. `IncidentAnalyst.explain` -> `Explanation` (§7.2): grounded summarization / triage / reasoning / remediation. Every `[ref]` the summary cites must be a real evidence ref (one repair turn); no LLM key / outage / timeout / ungrounded / oversized context -> a deterministic factual template with `degraded=true`. Holds no tools, takes no action; `recommendations` are a fixed vetted per-subject list, never model-authored. `api-gateway` `GET /api/v1/soc/detections/{id}/explanation`. |
| Multi-agent defense (Unit 4) | `sm_ai.agents` — `AgentSpec` (name + fixed system prompt + tool **allow-list**); `run_agent` under `AgentLimits` (`max_steps` / `max_tool_calls` / `wall_clock_s` / token `RunBudget`) + a cancellation `Event`. `DETECTION_AGENT` / `THREAT_INTEL_AGENT` / `RESPONSE_AGENT`. An agent **cannot spawn another agent** and **cannot execute**; a tool outside its allow-list or unauthorised is refused mid-run without stopping the run; a tool exception is a tool result, not a crash. The agent principal holds **no standing permissions**. `RESPONSE_AGENT` emits `ProposedAction`s; `action_gate(action, response_mode, approval_required, is_production, policy_signed)` -> `denied` under `suggest_only`, otherwise `approval_required` unless (auto + no approval + production + signed policy + reversible) -> `allowed` — never reachable with the shipped defaults. `services/ai-analyst` `POST /api/v1/agents/run`. |

### Verification performed (local, 2026-09-10)

- `ruff check` clean; `mypy --strict` over all 16 src trees (303 files) clean;
  **658 unit tests** (`sm_ai`: adapters / client / tokens / registry / evidence /
  prompt / sanitize / agents = 79; `ai-analyst`: analyst / explain-route /
  agents-route = 33) + `gen_contracts.py --check` (no `contracts-ts` /
  `contracts-py` drift).
- Real infra: `tests/integration/test_soc_reads_pg.py` **4 pass** against real
  PostgreSQL 16 (the api-gateway SOC repository the explanation endpoint reads
  through).
- `docker build -f deploy/docker/Dockerfile.app` builds; `sm_ai` + `sm_ai_analyst`
  import in the image.
- **CI green on a clean runner — all five jobs, final run `34432159191`**
  (earlier unit runs `34429226626` / `34429715242` / `34430968254`).

### Pre-output engineering review (Constitution §23)

- **The LLM is not trusted (the phase's CRITICAL SECURITY clause).** It has no
  capability of its own. Every tool goes through `ToolRegistry.invoke`, which
  checks the tool exists, then that the **caller's principal** holds the tool's
  `required_permission` — a well-formed tool call the model produced for a real
  tool is still refused if the principal lacks the permission
  (`test_an_unauthorized_call_is_denied_even_though_the_llm_asked`). The analyst
  holds no tools at all; the defense agents run under `_AgentPrincipal`, which
  returns `False` for every permission.
- **Prompt injection / context poisoning.** `EvidenceBuilder` fences every
  non-trusted item with `fence_untrusted` (nested delimiters broken up, size
  capped) and records `scan_for_injection` hits per ref; the system turn tells
  the model the fenced content is inert; `build_grounded_messages` guarantees
  evidence never lands in the system turn (asserted by a test). An injection
  string in the evidence is answered (fenced) and flagged, not obeyed
  (`test_injection_in_evidence_is_flagged_but_still_answered`).
- **Data exfiltration.** The audit record carries `prompt_sha256`, never the
  prompt text. `HttpLlmBoundary` sends only the assembled request to the
  configured base URL and is inert without a key. `SM_LLM_API_KEY` is a secret
  config field; nothing logs it.
- **Tool abuse / malformed input.** Args are validated against the tool's
  Pydantic model (`ToolInputInvalid`); tool output is validated against its
  result model (`ToolOutputInvalid`) — a tool bug is surfaced, not fed back to
  the model. An agent asking for a tool outside its spec's allow-list gets an
  error tool-result and the run continues.
- **Privilege escalation / unauthorized actions.** The response agent produces
  `ProposedAction`s only. `action_gate` is a pure function; with the shipped
  `SM_RESPONSE_MODE=suggest_only` + `SM_RESPONSE_APPROVAL_REQUIRED=true` it
  returns `denied`. Even `auto` needs production + a signed policy + a reversible
  action, and an irreversible action is always `approval_required`
  (`test_action_gate_truth_table`, `test_action_gate_never_allows_an_irreversible_action_without_review`).
- **Uncontrolled recursion / runaway cost.** `run_agent` enforces `max_steps`,
  `max_tool_calls`, a wall-clock deadline (`asyncio.wait_for` per LLM call plus a
  per-step check), and a cumulative-token `RunBudget` on the `LlmClient`. An
  agent cannot invoke `run_agent` — there is no tool for it and the runner takes
  a flat `AgentSpec`, not a graph. Each limit has a test that trips it.
- **Failure isolation.** A tool exception inside the loop is caught and returned
  to the model as `error: ...`; an LLM error after retries ends the run with
  `status="failed"` and a `detail`, never an unhandled exception. `ai-analyst`
  is HTTP-only with no DB / Kafka, so it cannot take a shared dependency down.
- **Never claim a live-provider result.** `LlmResponse.from_live_provider` and
  `AnalystModelInfo.from_live_provider` are `False` for every path in this build;
  `Explanation.degraded` / `AgentRunResult.status` say so. The docs and the
  service READMEs state no live LLM has been called.
- **Grounding.** Every sentence of an `Explanation.summary` must cite an evidence
  ref that is in the request; an uncited or unknown-ref answer gets one repair
  turn, then the deterministic template. Agent findings carry the evidence refs
  parsed from their `[...]` citations.

### Deferred (deliberately)

- **A live LLM provider.** `HttpLlmBoundary` is real but unexercised — no
  credentials (ADR-014). The deterministic adapter is the only tested path.
- **`agent-orchestrator` as a service**, the `agent.tasks` Kafka bus, Postgres
  `agent_task` / `analyst_message` / `explanation` / `response_action` state, and
  an inter-agent comms protocol. Unit 4 is a single flat agent run per request.
- **Response execution** — EDR / firewall / SOAR adapters, blast-radius and
  rollback computation, `POST /api/v1/response/actions`. Proposals + the gate
  verdict only. **NOT VERIFIED — REQUIRES ACTUAL INTEGRATION.**
- **Pre-generation** — no `detections` / `attack_chains` consumer; the analyst
  and agents are on-demand via `api-gateway`.
- **The analyst chat endpoint** and the frontend analyst / agent-activity panels.

### Exit criteria status

| Criterion | Status |
|---|---|
| LLM provider abstraction; no creds -> real boundary + deterministic test adapter | OK `sm_ai.provider` / `DeterministicAdapter` / `HttpLlmBoundary` (inert without a key) |
| AI analyst: evidence/context builder, summarization, triage, reasoning, remediation | OK `services/ai-analyst` — grounded, `degraded` template fallback |
| detection / threat-intel / response-orchestration agents | OK `sm_ai.agents` — 3 specs + `run_agent` + `POST /api/v1/agents/run` |
| the LLM is NOT trusted; defend against injection / exfil / tool abuse / priv-esc / unauthorized actions / context poisoning | OK deny-by-default `ToolRegistry`, fenced evidence, no standing permissions, `action_gate` never `allowed` |
| every tool: schema, authorization, input + output validation, audit logging | OK `Tool` / `ToolRegistry` |
| the AI must never gain privileges because an LLM requested them | OK re-checked against the caller's principal; test asserts it |
| controlled orchestration; timeouts / token limits / cancellation / retry / failure isolation; no uncontrolled recursion | OK `AgentLimits` + `RunBudget` + cancel `Event`; each limit tested; agents cannot spawn agents |
| never claim live provider verification unless verified | OK `from_live_provider` False everywhere; docs say so |
| tests: prompt injection, unauthorized tool call, malformed tool input, evidence grounding, LLM timeout, provider outage, audit logging | OK covered |
| **CI green on a clean runner** | OK **all five jobs — final run `34432159191`** (unit runs `34429226626` / `34429715242` / `34430968254`) |

## Phase 9 exit report

**State: COMPLETE / CI-VERIFIED (all five jobs incl. `frontend`, final run
[`34428106928`](https://github.com/gaurav685/sentinelmesh/actions/runs/34428106928)).**
Units 1–4 commits `15f5d1c` / `790fdf5` / `dac8e50` / `3d8c401`.
Earlier unit runs `34424869328` / `34426774409`.

**No attack activity is fabricated anywhere in the UI. Demo/absent data is
labelled in plain language ("no ATT&CK catalog imported", "external provider
adapters are feature-flagged off", "an empty result means no such relationships
have been observed"). The frontend never re-declares a backend shape — every type
is generated from the canonical contracts. Frontend authorization is display-only;
`api-gateway` stays server-authoritative. No secret ships in the bundle; the
session is an httpOnly cookie.**

### Delivered (Units 1–4)

| Area | State |
|---|---|
| SOC BFF (Unit 1) | `api-gateway` is the browser-facing read API. `sm_contracts.api.soc` — `SocSummary` (real per-tenant counters), `RiskSubject`, `MitreHeatmap`, `TimelineResponse`; `CursorPage[…]` exports. `GET /api/v1/soc/*` — Postgres reads (`SqlSocRepository`, keyset-paged, `WHERE tenant_id = :principal_tenant`) for detections / alerts / risk / summary / heatmap / timeline; minted-JWT proxies (`InternalServiceClient`, tenant scoped to the caller) for chains / graph / threat-intel. Every route `require_permission(detections:read | hunt:query)`; a dependency outage → HTTP 503, never a 500 or a fabricated result. |
| Frontend scaffold + typed client (Unit 2) | `packages/contracts-ts` emits a single `src/index.ts` from a combined `$defs` schema (`jsonschema.py` `ref_template` fixed to `#/$defs/` — the TS pipeline had never worked before). `frontend/web` — Next.js 15 App Router + TS. Typed `apiFetch` (`credentials: "include"`, CSRF header on mutations, `ApiError.kind` → a UI state). `AuthProvider` hydrates `/auth/me`; `middleware.ts` is a redirect-only guard. `AppShell`, `Loading` / `EmptyState` / `ErrorState`, `Severity` (colour + text + shape). CSP + security headers; `react/no-danger` is an error. New CI `frontend` job. |
| SOC views (Unit 3) | Real typed views for every read surface: dashboard, alerts + `incidents/[id]` (fetches the triggering detection — rule id, evidence, techniques), attack-chain list + `chains/[id]` (kill-chain stage table), MITRE heatmap, risk heatmap, entity explorer + `entities/[id]` timeline, threat-intel indicators. `DataView<T>` renders loading / error / empty / ready in one place. `src/lib/contract.test.ts` compile-checks fixtures against the generated types. CI `frontend` job's drift check switched from the unsupported `git diff --exit-status` to `git diff --quiet`. |
| Attack graph + realtime + polish (Unit 4) | `sm_contracts.api.graph` — `GraphNode` / `GraphEdge` / `GraphNeighborhood` / `GraphPath` (promoted from the graph-service draft schemas so the browser consumes generated types). `api-gateway` `/soc/graph/{neighbors,paths}` now return those typed models. `frontend/web` `graph/page.tsx` — a Cytoscape explorer (lazy-loaded, client-only), node/edge detail panel, `truncated` warning, and an accessible node/edge **list fallback** that is the real representation for assistive tech and keyboard users. `useResource` gains an optional `refreshMs` poll + `updatedAt`; `LiveBadge` shows "Updated Ns ago · auto-refresh Ns" on the dashboard and alerts list — an honest client poll, never a claim of streaming. `prefers-reduced-motion` disables the pulse/spinner. Tests: `AttackGraph` (cytoscape mocked — element mapping, dangling-edge drop, tap → `onSelect`, init-failure fallback), `graph/page` (BFF query, truncation, selection, empty), `LiveBadge`. |

### Verification performed (local, 2026-09-10)

- `frontend/web`: `npm run lint` clean; `npm run build` OK (14 routes); `npm run test` **37 vitest tests** pass (component, API-contract, auth-flow, graph-interaction).
- Python: `ruff check .` clean; `mypy --strict` over `packages/contracts-py/src` + `services/api-gateway/src` clean; **594 unit tests** + `gen_contracts.py --check` (JSON Schema up to date, no `contracts-ts` / `contracts-py` drift); `tests/contract/test_ci_config.py` 14 pass.
- Real infra: `tests/integration/test_soc_reads_pg.py` **4 pass** against real PostgreSQL 16 (`SqlSocRepository` tenant-scoped reads). Neo4j-backed graph tests (`test_graph_intel_neo4j.py`, `test_graph_service_neo4j.py`) **skipped locally** — the fixture's 3 s bolt-connect probe times out under the Windows proactor loop; unchanged graph-service code, CI (Linux) is the confirmation.
- `docker build -f deploy/docker/Dockerfile.app` builds; `docker run … python -c "import sm_api_gateway.app, sm_contracts"` OK.
- **CI green on a clean runner — all five jobs (`static` / `unit` / `integration` / `image` / `frontend`), final run `34428106928`; earlier unit runs `34424869328` / `34426774409`.**

### Pre-output engineering review (Constitution §23)

- **Do not fabricate attack activity; demo data must be labelled (§3 + the phase brief).** No view invents a detection, chain, indicator or edge. Every empty state names the missing upstream. There is no seeded "demo attack" in the frontend at all; the `demo-badge` CSS class exists for when labelled demo data is introduced, and is currently unused.
- **Frontend authorization never replaces backend authorization.** `hasPermission` in `auth.tsx` only filters nav items and hides buttons — it is documented "DISPLAY ONLY". Every `/api/v1/soc/*` route is `require_permission(...)` in `api-gateway` (deny-by-default, metered + audited). `middleware.ts` only redirects a request with no session cookie to `/login`; it makes no allow decision. The graph endpoints additionally require `hunt:query`.
- **No backend schema is duplicated.** Every response type is imported from `@sentinelmesh/contracts`, generated from the same JSON Schema the backend validates against. The graph-query shapes that had lived only in `graph-service/schemas.py` are now `sm_contracts.api.graph`; `api-gateway` validates the proxied response against them (`response_model=GraphNeighborhood`), so a graph-service drift surfaces as a 500 in the BFF's own tests, not a silently-wrong UI. `contract.test.ts` fails the frontend build if a regenerated type no longer accepts a known-good fixture.
- **No secret in the frontend.** The session is an httpOnly cookie (`credentials: "include"`); no token is read or stored in JS. `next.config.mjs` sets a CSP. `SM_API_PROXY_TARGET` is a server-only rewrite target. Grep of the bundle for a key pattern is clean (build output has no `.env` inlining — only `NEXT_PUBLIC_*` is inlined and none is defined).
- **Tenant-aware UI.** The shell shows the tenant from `/auth/me`; every BFF read is scoped to `principal.tenant_id` server-side — the UI cannot request another tenant's data (there is no tenant parameter on any client call).
- **"Real time" is honest.** `LiveBadge` says "auto-refresh Ns" and "Updated Ns ago"; the code is a `setInterval` re-fetch. No WebSocket, no "live stream" claim (a test asserts the badge text contains neither "streaming" nor "live"). The gateway has no push channel yet — documented in R13 and here.
- **XSS / safe rendering.** `react/no-danger` is an ESLint **error**; there is no `dangerouslySetInnerHTML` anywhere. All backend text (titles, summaries, rationales, node properties) renders as React children (auto-escaped). Node `properties` are `String()`-coerced for display and never used for a routing or auth decision (documented on the contract).
- **Accessibility.** Severity is never colour-only (text + shape). Skip link, `role="status"`/`role="alert"` regions, `aria-current` nav, `aria-pressed` on the graph node list, `prefers-reduced-motion` honored. The Cytoscape canvas is `aria-hidden` with a full node/edge list beside it as the accessible equivalent.
- **Bounded / safe requests.** List endpoints cap `limit` server-side (≤ 200–1000); the graph depth is clamped 1–6 at the BFF and again at graph-service; a non-object graph-service response → 503, not a crash.

### Deferred (deliberately)

- **WebSocket / SSE realtime + `notification-service`.** The gateway exposes no push channel for the Kafka topics. Realtime is a poll. A projection service or an SSE endpoint over a Redis fan-out is a later phase.
- **Cinematic attack replay.** The `sm_ml.temporal` replay engine (P8) is the backend foundation; no replay UI yet.
- **Playwright e2e, axe-in-CI, visual regression, Lighthouse budgets.** Component/contract/flow tests (vitest) only for now.
- **Graph path-finding UI.** `sm_contracts.api.graph.GraphPath` + the BFF `/soc/graph/paths` endpoint are typed and wired; no frontend view consumes them yet.
- **`graph-service` `GraphIntelResponse` promotion.** The intel endpoint's response still lives in `graph-service/schemas.py`; the graph page does not surface intel yet.
- **Incident actions (acknowledge / assign / close).** The incident view is read-only; mutations are a later phase with their own permissions + CSRF.

### Exit criteria status

| Criterion | Status |
|---|---|
| authentication / dashboard / alert / incident / attack-graph / timeline / risk-heatmap / entity-explorer / threat-intel / MITRE / attack-chain views | ✅ all present, typed, with loading/error/empty states |
| real-time updates where supported | ✅ honest client poll + "last updated" indicator; WebSocket deferred (documented) |
| typed API clients generated from canonical contracts; no duplicated backend schemas | ✅ `@sentinelmesh/contracts` single generated `index.ts`; `contract.test.ts` guards drift |
| no hardcoded fake backend responses | ✅ every view fetches the BFF; empty/absent data is labelled |
| protected routes / server-authoritative authorization / safe token+session / XSS protections / no secrets in frontend / tenant-aware | ✅ httpOnly cookie + CSRF, `require_permission` server-side, `react/no-danger` error, CSP, tenant from `/me` |
| tests: component / API-contract / authentication / authorization-UI / critical-flow / graph-interaction | ✅ 37 vitest tests |
| **CI green on a clean runner** | ✅ **all five jobs — final run `34428106928`** (unit runs `34424869328` / `34426774409`) |

## Phase 8 exit report

**State: COMPLETE / CI-VERIFIED (all four jobs, runs
[`34408045416`](https://github.com/gaurav685/sentinelmesh/actions/runs/34408045416)
/ `34408494057` / `34409131977` /
[`34410178417`](https://github.com/gaurav685/sentinelmesh/actions/runs/34410178417))
against real PostgreSQL 16 + Redis 7 + Redpanda + Neo4j 5. Units 1–4 commits
`7de7a1f` / `356f11f` / `7ab38e5` / `41182f3`.**

**No accuracy / AUC / precision / recall / F1 number is produced or stored
anywhere. No dataset and no trained GNN weights ship (ADR-024). Every graph-model
contract carries `METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`;
the training pipeline's headline metric is the same string and `benchmark_verified`
is `false` for a fixture run. The `structural` graph detectors and the whole
`sm_ml.temporal` engine are standard-library and deterministic — the same input
always yields the same output.**

### Delivered (Units 1–4)

| Area | State |
|---|---|
| `sm_ml.graph` (Unit 1) | `GraphSample` (deterministic, numpy-free — node features are a pure function of the edge set + a temporal window; edges sorted so output is arrival-order-independent; a malformed sample raises `ValueError`). Versioned `GraphFeatureSchema` (`GRAPH_FEATURE_SCHEMA_VERSION = "1"`). Model interface `NodeAnomalyResult` / `SubgraphVerdict` / `ClusterResult` (each carries `model_version` + explicit `confidence`). Always-available: `StructuralGraphAnomaly` (MAD z-score + stdev floor so a lone outlier in a uniform crowd is still caught), `SuspiciousSubgraphHeuristic`, `ConnectedComponentClusterer` / `LabelPropagationClusterer`. GNN boundary: `GnnNodeAnomalyModel` + `GRAPHSAGE_SPEC` / `GAT_SPEC` (`sm-ml[gnn]` optional, not in CI; torch absent → `GraphModelUnavailable`, no weights → `GraphModelNotTrained`). `GraphModelRegistry`. `ml/models/{graphsage,gat,graph_anomaly}/CONTRACT.md`. |
| `sm_ml.temporal` (Unit 2) | `TemporalEvent`; `EventTimeline` (bisect-ordered, `event_id` de-dup, out-of-order sorted, clock-skew clamped + counted, `gaps()` for missing data — order-independent); `TemporalGraphState.at(t)` (a pure fold → historical graph state → `GraphSample`); `build_progression` (furthest kill-chain stage over time, never regresses); `replay` + `ReplayCursor` (deterministic windowed re-emission); `stitch_sessions` (union-find over shared-entity + temporal proximity). Config `SM_TEMPORAL_MAX_CLOCK_SKEW_SECONDS` / `SM_TEMPORAL_SESSION_LINK_SECONDS`. |
| `services/ml-training` (Unit 3) | The reproducible `dataset → preprocessing → graph construction → feature generation → training → validation → checkpoint → model version → inference → evaluation` pipeline (offline CLI `sm-ml-train`). `TrainingConfig.config_hash()` (byte-identical artifacts) + `model_version()`. `synthetic_fixture_dataset` (labelled toy graph — a plumbing check); `load_dataset` for a real JSON-lines benchmark with an id + sha256. `structural` trains fully offline (calibrates the z-threshold against the labelled train split); `graphsage` / `gat` → `PipelineSkipped` without torch, no artifact written. `ModelMetadata` records seed / versions / dataset id + sha256 / git commit / `EvaluationReport` (`headline_metrics: NOT VERIFIED`). `write_artifact` writes the `GraphModelRegistry` layout. Config `SM_ML_SEED` / `SM_GRAPH_ANOMALY_Z` / `SM_ML_GRAPH_MODEL_DIR`. |
| Serving + intel (Unit 4) | `ml-inference`: `GraphModelHost` + `POST /api/v1/infer/graph/{model}` (structural always available as a builtin; a GNN name → 503 `MODEL_UNAVAILABLE` when its artifact or torch is missing; a malformed graph → 422, never a 500) + `GET /api/v1/graph/models`; `/readyz` reports the graph catalog. `graph-service`: `GET /api/v1/graph/intel?label=&key=&depth=` runs `StructuralGraphAnomaly` + `LabelPropagationClusterer` + `SuspiciousSubgraphHeuristic` over a bounded, tenant-scoped neighbourhood (`sm-ml` added as a dependency). CI: `ml-training` in the static mypy trees + all three install blocks (not the image). |

### Integration verification

- `tests/integration/test_graph_intel_neo4j.py` (real Neo4j) — a fan-out hub written via `GraphWriter`, read back via `GraphRepository.neighbors`, is flagged by `analyse_neighbourhood` and the neighbourhood forms one cluster.
- `test_graph_pipeline_e2e.py` / `test_chain_pipeline_e2e_pg.py` (carried from earlier phases) still green — the graph the intel layer reads is the one the earlier pipeline writes.

### Pre-output engineering review (Constitution §23)

- **Do not fabricate metrics (§3).** No accuracy / AUC / F1 / precision / recall / latency / throughput number appears in `sm_ml.graph`, `sm_ml.temporal`, `ml-training`, the graph-model contracts, the serving endpoints, or the docs. `ml-training`'s `EvaluationReport.headline_metrics` is the literal `NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION` and `benchmark_verified` is `false` for a fixture run; `val_metrics` are present but every path that surfaces them labels them a *plumbing check, not a performance claim*.
- **Determinism.** `GraphSample` sorts nodes and edges, so its feature matrix and any model output are independent of arrival order. `StructuralGraphAnomaly` / the clusterers / the temporal engine use no clock and no RNG. `ml-training` seeds `random` (and `torch` when present) from `TrainingConfig.seed`; `config_hash()` excludes only `output_dir`, so two runs with the same config + dataset write byte-identical `model.json`. Tests assert each of these.
- **Model-load failure is safe and observable (the phase's FAILURE section).** A GNN whose artifact or `torch` is missing raises a typed `GraphModel*` error; `ml-inference` maps it to HTTP 503 `MODEL_UNAVAILABLE` with a `model` detail (never a 500), a metric fires, and `graph-service`'s intel path never calls a GNN at all — it runs the stdlib structural models, which cannot be unavailable. `ml-training` writes nothing on `PipelineSkipped`. No unrelated service is affected: the graph models are optional everywhere they are used.
- **Out-of-order / duplicate / clock-skew / missing (temporal).** `EventTimeline` handles all four explicitly and counts the corrections (`skew_corrected`, `duplicates_dropped`); `gaps()` surfaces missing data rather than hiding it. `replay` is read-only and rejects an inverted window.
- **Never claim certainty.** `SubgraphVerdict.score` is bounded `[0,1]` and documented as a likelihood; `NodeScore.normalized_score` is validated in `[0,1]`; `confidence` on every result defaults to `0.0` until an evaluation run calibrates it.
- **No ATT&CK-coverage claim.** The temporal `build_progression` reuses `sm_contracts.stage_for_technique`, which returns `AttackStage.unknown` for anything outside SentinelMesh's own rule techniques — carried over unchanged from Phase 7.
- **Tenant isolation.** `graph-service`'s intel endpoint takes the tenant from the verified JWT and reads through `GraphRepository`, which scopes every Cypher traversal to that tenant (Phase 4 guarantee). `ml-inference`'s graph endpoint scores whatever graph the caller submits — it holds no tenant data.
- **Bounded resources.** The intel neighbourhood read is depth-clamped and row-capped by the repository; `GraphInferRequest` caps nodes at 20 000 and edges at 100 000; `LabelPropagationClusterer` has a fixed iteration cap.

### Deferred (deliberately)

- **A trained GNN.** The GraphSAGE/GAT boundary, the training pipeline, the registry, and the serving endpoint are all real; the weights are not. Needs a real graph dataset + GPU (external, ADR-024).
- **A streaming graph-intelligence job.** `graph-service`'s intel endpoint is pull-only. A consumer that scores the graph on `graph.events` and emits findings is a later phase.
- **A predictive forecast.** `{predicted_action, probability, horizon, confidence}` and a trained sequence model. The temporal progression track + GNN embeddings are the foundation (R15).
- **`temporal-stitcher` as a service** and a `graph-service` `GET /timeline/{entity}` endpoint — wired when Phase 9's UI needs them.
- **`torch` in CI** — deliberately excluded; the structural path is what CI verifies.

### Exit criteria status

| Criterion | Status |
|---|---|
| GraphSAGE / GAT | ✅ `GnnNodeAnomalyModel` + specs + registry + serving boundary (weights external) |
| graph anomaly detection | ✅ `StructuralGraphAnomaly` (always) + GNN reconstruction-error path |
| suspicious subgraph classification | ✅ `SuspiciousSubgraphHeuristic` + `graph-service` intel endpoint |
| threat-cluster discovery | ✅ `ConnectedComponentClusterer` / `LabelPropagationClusterer` |
| temporal analysis / historical replay / cross-session stitching | ✅ `sm_ml.temporal` (`EventTimeline` / `TemporalGraphState.at(t)` / `replay` / `stitch_sessions`) |
| predictive attacker modeling foundation | ✅ `ProgressionTrack` + `TemporalGraphState` + GNN embeddings; no forecast yet |
| reproducible pipeline with seeds / config / metadata / schema / versioning / artifacts | ✅ `services/ml-training` end to end on a fixture |
| do not fabricate metrics | ✅ `NOT VERIFIED` everywhere; fixture metrics labelled a plumbing check |
| model-load failure → fail safely + observable error + degraded behaviour + no crash of unrelated services | ✅ `MODEL_UNAVAILABLE` 503 / `PipelineSkipped` / structural fallback; unit + integration |
| tests: graph preprocessing / feature generation / deterministic inference / model loading / malformed features / temporal ordering / replay / cross-session stitching | ✅ `test_graph_construct` / `test_graph_models` / `test_temporal` / `test_pipeline` / `test_infer_graph` / `test_intel` / `test_graph_intel_neo4j` |
| **CI green on a clean runner** | ✅ **all four jobs — runs `34408045416` / `34408494057` / `34409131977` / `34410178417`** |

## Phase 7 exit report

**State: COMPLETE / CI-VERIFIED (all four jobs, run
[`34406870398`](https://github.com/gaurav685/sentinelmesh/actions/runs/34406870398))
against real PostgreSQL 16 + Redis 7 + Redpanda + Neo4j 5. Units 1–3 commits
`daaf20e` / `8c3a177` / `8f4becb`.**

**A chain is a *correlation*, never a verdict. `confidence` is bounded at 0.95 —
the platform never claims certainty about an attack. Stage assignment is a
deterministic lookup; a technique with no known mapping is `AttackStage.unknown`,
not a guess. `TECHNIQUE_STAGE` covers only the techniques SentinelMesh's own
rules emit — not a claim of ATT&CK coverage. The chain threat score is a fixed,
documented, versioned weighting (`CHAIN_SCORE_VERSION = "v1"`) — no validated
scoring performance is claimed anywhere.**

### Delivered (Units 1–3)

| Area | State |
|---|---|
| `sm_contracts.chains` | `AttackStage` (14 ATT&CK-tactic kill-chain stages + `unknown` as a first-class value), `STAGE_ORDER`, `TACTIC_STAGE` (stable ATT&CK tactic ids) / `TECHNIQUE_STAGE` (SentinelMesh's own rule techniques only), `stage_for_tactic` / `stage_for_technique` / `stages_for_techniques`; `ChainStatus` (forming / active / dormant — never auto-`confirmed`); `ChainStageModel` / `AttackChainModel` / `AttackChainPayload` (on `attack_chains`, `EventType.attack_chain_updated`); `chain_dedup_key` / `chain_window_start` (fixed tumbling window → deterministic under redelivery + out-of-order) / `chain_id_for`; `CONFIDENCE_CEILING = 0.95`. **STABLE.** |
| `migrations/postgres/0005` + `chain_models` | `attack_chain` / `attack_chain_stage` — CHECK constraints from the contract enums, deterministic id + `(tenant, subject_type, subject_id, window_start)` unique, one stage row per `(chain, stage)`, `attack_chain_stage` `ON DELETE CASCADE`; `max_detection_score` per stage, `ti_corroborated` per chain. |
| `services/correlation-engine` (port 8009) | Consumes `detections` (group `correlation`). `staging.py` places each detection on the furthest non-`unknown` kill-chain stage its techniques imply (`rule.ti.*` → TI-corroborated, no technique). `chains.py` `ChainRepository.correlate` upserts the deterministic-id chain + its `attack_chain_stage` rows (detection ids as a set → idempotent redelivery; `min`/`max` timestamps → out-of-order safe; `ti_corroborated` monotonic), recomputes `progression` / probabilistic `confidence` (≤ 0.95; discounted when stages ran backwards in time) / `ChainStatus`, runs `scoring.py` `score_chain` (`CHAIN_SCORE_VERSION` weighting over severity + anomaly + threat-intel + progression + confidence; optional asset-criticality / identity-risk renormalise the weighting), and writes `threat_score` for the entity subject. `engine.py` emits `AttackChainPayload` on `attack_chains` **and** `graph.py` `graph.commands` (`:AttackChain` node, `INVOLVES` → subject, `MAPPED_TO` → `:AttackTechnique`). Read API `GET /api/v1/chains[/{chain_id}]` (internal-JWT, tenant from token). Poison → `detections.dlq`; DB / produce failure → retried. |
| `services/mitre-service` | Now consumes `attack_chains` as well as `detections` (one group, one consumer, dispatch on `event_type`). A chain's mapping subject is `attack_chain`; its rationale names the chain and its detection count. |
| `services/detection-engine` | No longer writes `threat_score` — `correlation-engine` is the sole writer (it sees the whole chain). `DetectionPayload` now carries `subject_type` / `subject_id`, populated in `_emit`. |
| Wiring | `correlation-engine` in `Dockerfile.app` (COPY + `pip install`), `docker-compose.yml` (`detect` profile, port 8009, group `correlation`), CI (installs in all three jobs, 13th `mypy` tree, image entrypoint-import). `test_deploy_local_config` PROFILED. Topic registry: `correlation` + `mitre-mapping` on `detections`; `correlation-engine` producer + `mitre-mapping` consumer on `attack_chains`; `correlation-engine` producer on `graph.commands`. Config `SM_CHAIN_WINDOW_SECONDS` / `SM_CHAIN_DORMANT_SECONDS` / `SM_CHAIN_SCORE_ALERT_THRESHOLD` / `SM_CORRELATION_ENGINE_URL`; `.env.example` updated. |

### Integration verification

- `test_chain_models_pg.py` — the `0005` CHECK / uniqueness / cascade constraints.
- `test_chain_correlation_pg.py` (real PostgreSQL) — kill-chain ordering, duplicate-detection idempotency, out-of-order flagging + confidence discount, incomplete `forming` chain, dormancy, tumbling-window separation, tenant isolation, TI monotonicity + score lift, degraded-member scoring.
- `test_chain_pipeline_e2e_pg.py` (real PostgreSQL + real Neo4j) — an auth-failure burst → `detection-engine` → `detections` → `correlation-engine` → one `attack_chain` with a `credential_access` stage, exactly one `threat_score` row (weights version `"v1"`, proving `detection-engine` no longer writes it), and `graph.commands` that, applied via `GraphWriter`, create the `:AttackChain` node with `INVOLVES` → `:Identity` and `MAPPED_TO` → `:AttackTechnique {T1110}`.

### Pre-output engineering review (Constitution §23)

- **Never claim certainty when evidence is probabilistic (§3).** `confidence` is bounded by `CONFIDENCE_CEILING = 0.95` in the contract, the scorer, and the DB CHECK. `ChainStatus` has no `confirmed` value — confirmation is a human action on the alert/investigation layer, and the correlator never asserts it. The chain title/notes state facts (stage list, detection counts, "out_of_order_observed") — never a conclusion.
- **Deterministic, versioned scoring (req 8).** `score_chain` is a pure function of `(max_severity, max_detection_score, ti_corroborated, progression, confidence, degraded, asset?, identity?)` — fixed weights, no clock, no RNG, `CHAIN_SCORE_VERSION` stamped on every `threat_score` row and `AttackChainPayload`. `chain_progression` and `chain_confidence` are likewise pure. Asset-criticality and identity-risk are accepted as inputs and renormalise the weighting when supplied; no registry feeds them in this phase, and their absence is not a fabrication — the components dict simply omits them.
- **No fabricated ATT&CK coverage.** `stage_for_technique` returns `AttackStage.unknown` for anything outside the small, auditable `TECHNIQUE_STAGE` map (the techniques `detection-engine`'s own rules emit). A chain that is mostly `unknown` stages is flagged (`mostly_unmapped_techniques`) and its score degrades. `mitre-service` still validates a chain's technique ids against the imported catalog — off-catalog ids are `unmapped`, never guessed.
- **Out-of-order / duplicate / missing (the phase's "handle" list).** Duplicate detection → set-valued `detection_ids`, a redelivery is a no-op (`new_detection == False`), aggregates unchanged, same score. Out-of-order → `first_seen`/`last_seen` widened by `min`/`max`; a stage transition that runs backwards in kill-chain order over time is counted and discounts `confidence` and adds an `out_of_order_observed` note. A missing intermediate stage → `progression` still reflects the furthest stage reached; `distinct_stage_count` is honest about the gap. Clock skew is bounded upstream by the envelope's `_time_sanity` validator (±5m); the tumbling window is wide (24h default) relative to skew.
- **Idempotency.** `chain_id_for(chain_dedup_key(...), chain_window_start(...))` is `uuid5` — the same detection always lands in the same chain row; `graph_command_id(chain_id, op, label, disc)` is deterministic so `graph-writer` dedups a re-emitted projection.
- **Tenant isolation.** Every `attack_chain` / `attack_chain_stage` / `threat_score` row carries the detection's `tenant_id` (from the event, never a field). The FK is `RESTRICT`. `chain_dedup_key` embeds the tenant. `get_chain` / `list_chains` filter by `tenant_id`; the read API takes the tenant from the JWT. Integration test: two tenants with the same subject get separate chains, and a cross-tenant `get_chain` returns `None`.
- **Degrade, never drop.** `correlation-engine` emits `attack_chains` and `graph.commands` on every processed detection; a produce failure is a `TransientError` (retry), never a silent drop. A DB failure is likewise retried. An unparseable / wrong-type record → `PoisonError` → `detections.dlq`. `mitre-service` keeps its existing "catalog absent → everything `unmapped`" degraded path for chains too.
- **Handoff safety.** `detection-engine` dropping its `threat_score` write and `correlation-engine` picking it up ship in one commit; the `uq_threat_score_subject` upsert means the last writer wins cleanly. A detection that raises no chain-relevant technique still forms a chain (stage `unknown`) and still produces a `threat_score` — the entity is never left unscored.

### Deferred (deliberately)

- **A max-across-active-chains / time-decay entity score.** Today `threat_score` is the most-recently-updated chain's score for that subject. A subject with several concurrent chains, or a chain that has gone dormant, is not yet reconciled into a single decaying entity score.
- **`HAS_STAGE` graph edges / stage nodes.** Stages live in Postgres; the graph carries the chain node, `INVOLVES`, and `MAPPED_TO` only.
- **Asset-criticality & identity-risk inputs.** The scorer's signature is ready; no registry service produces these values yet.
- **Cross-window chain merge.** An APT that spans two 24h windows is two chains. A "stitch adjacent chains for the same subject" pass is Phase 8 territory (cross-session stitching).
- **`attack_chains` consumers beyond `mitre-service` / graph.** `ai-analyst`, `memory`, `reporting` are later phases.

### Exit criteria status

| Criterion | Status |
|---|---|
| attack-stage model / chain model / evidence links / temporal ordering / confidence / technique mapping | ✅ `sm_contracts.chains` + `attack_chain` / `attack_chain_stage` |
| lateral movement / credential escalation / exfiltration-path representation | ✅ ATT&CK-tactic stages incl. `lateral_movement` / `privilege_escalation` / `credential_access` / `exfiltration`; kill-chain ordering + `progression` |
| incomplete chains / conflicting evidence / out-of-order / duplicate detections | ✅ `forming` status, `conflicting_severity` / `out_of_order_observed` notes, `min`/`max` timestamps, set-valued stage membership — integration-verified |
| never claim certainty | ✅ `CONFIDENCE_CEILING = 0.95` (contract + scorer + DB CHECK); no auto-`confirmed` |
| deterministic, documented, versioned scoring | ✅ `score_chain` (`CHAIN_SCORE_VERSION`); pure `chain_progression` / `chain_confidence` |
| scoring factors where architecture supports them | ✅ severity / anomaly / threat-intel / progression / confidence wired; asset-criticality / identity-risk accepted + renormalised, no registry yet |
| do not fabricate validated performance | ✅ no accuracy / F1 / precision / recall number anywhere |
| tests: construction / ordering / duplicate / incomplete / scoring / boundaries / determinism / tenant isolation | ✅ `test_staging` / `test_scoring` / `test_engine` / `test_graph` / `test_chain_correlation_pg` / `test_chain_pipeline_e2e_pg` |
| **CI green on a clean runner** | ✅ **all four jobs — run `34406870398`** |

## Phase 6 exit report

**State: COMPLETE / CI-VERIFIED (all four jobs, run
[`34366970151`](https://github.com/gaurav685/sentinelmesh/actions/runs/34366970151))
against real PostgreSQL 16 + Redis 7 + Redpanda + Neo4j 5. Local gauntlet: ruff,
`mypy --strict` over 12 src trees (224 files), 480 unit tests +
`gen_contracts --check`, 117 real-infra integration tests, `Dockerfile.app`
build. Units 1–5 commits `b468eca` / `9778fb7` / `1da61e1` / `43cbcc5` /
`9d777f8`.**

**Threat intelligence and ATT&CK coverage are exactly what is imported / stored —
nothing is fabricated. No ATT&CK STIX bundle ships in the repo (ADR-024); the
tests run on a labelled fixture bundle (`tests/fixtures/attack_mini_bundle.json`
— 2 tactics, 3 techniques, 1 sub-technique). No current-ATT&CK-version claim
appears anywhere. External TI providers are feature-flagged off by default
(`SM_TI_PROVIDERS` empty → zero outbound calls).**

### Delivered (Units 1–5)

| Area | State |
|---|---|
| `sm_contracts.mitre` | `AttackTactic` / `AttackTechnique` / `AttackMatrixVersion` / `TechniqueMapping` (`TenantScoped` + `TimestampedModel`, persisted) / `TechniqueMatch` (mapping-API result); `MappingConfidence` / `MappingSource` (rule/graph/feature/llm/analyst — LLM never authoritative alone) / `MappingSubjectType`; `TECHNIQUE_ID_RE`, `is_technique_id`, `parent_technique_id`. **STABLE target.** |
| `sm_contracts.threatintel` | `ThreatIndicator` (mandatory `Provenance`, `reputation` 0..1, derived `freshness`, nullable `tenant_id`) / `ThreatActor` / `TiCampaign` / `TiSource` / `EnrichmentMatch` / `Provenance`; `TiUpdatePayload` on `ti.updates` (`EventType.ti_indicator_updated`); `IndicatorType` / `IndicatorFreshness` / `TiConfidence` / `TiSourceKind` (incl. `FIXTURE`) / `TiUpdateAction`; `normalize_indicator_value` **rejects malformed (`ValueError`), never fabricates** (TB-4); `indicator_dedup_key` (global vs tenant); `freshness_for`. **STABLE target.** |
| `migrations/postgres/0004` + models | `attack_tactic` / `attack_technique` / `attack_matrix_version` / `technique_mapping` / `threat_indicator` / `threat_actor` / `ti_campaign` / `ti_source`. Enum/range CHECK constraints from the contract enums, `dedup_key` unique, `uq_technique_mapping_subject_technique_source`, partial index on `threat_indicator.expires_at`, `updated_at` triggers. Reversible downgrade. |
| `services/mitre-service` (port 8008) | `stix.py` (STIX 2.1 bundle → tactics / techniques / sub-techniques + `AttackMatrixVersion` with `stix_bundle_sha256` and **real** counts; `ValueError` on a non-bundle); `CatalogRepository.import_catalog` (delete + re-add per version in one transaction); `MappingEngine.map_techniques` validates candidate `technique_ids` against the imported catalog — unknown or deprecated → `unmapped`, **never guessed** — and `persist` upserts `technique_mapping`; consumes `detections` (group `mitre-mapping`, poison → DLQ); `GET /api/v1/mitre/{techniques,heatmap}` + `POST /map` (internal-JWT, tenant from token); `/readyz` flags an empty catalog. `scripts/import_attack_stix.py` CLI. |
| `services/threat-intel-service` (port 8007) | `IndicatorRepository` — IOC system of record; dedup on `indicator_dedup_key`, first/last-seen widened on re-observe, deterministic `reputation_score` (fixed base-by-confidence + malicious/benign tag deltas, clamped `[0,1]`), freshness derived on read, `sweep_expired` + `ExpirySweeper` emitting `ti.updates` (`expired`). Providers: `ProviderAdapter` (`asyncio.wait_for` per-attempt timeout, backoff retry, HTTP 429 → longer backoff, malformed row dropped-and-logged never ingested, outage → `ProviderResult(ok=False)` + metric); `FixtureProvider` labelled `source_kind=FIXTURE`, deterministic; `abusech` / `otx` external adapters, feature-flagged off. `ProviderPoller` upserts + emits `ti.updates` + records `ti_source`. Internal API `POST /api/v1/ti/{enrich,indicators}` + `GET /indicators` (a bad value → 422). Every indicator carries a `Provenance`. |
| `services/normalization-engine` (Unit 5) | `ThreatIntelEnricher` (an `Enricher`) — collects a canonical event's IP (v4/v6 by `ipaddress`), domain, and `hash_sha256`-by-length lookups, mints an internal token (`subject=normalization-engine`, `tenant_id=uuid(int=0)`, `audience=threat-intel-service`), calls `POST /api/v1/ti/enrich`, writes `enrichment["threat_intel"] = {provider, as_of, matches}` (genuine non-expired hits only). Any TI-service failure → `{}` (the runner records the provider unavailable; the event is **not** failed, R2). Feature-flagged `SM_TI_ENRICHMENT_ENABLED` (default off); the httpx client is lifespan-owned. |
| `services/detection-engine` (Unit 5) | Rule `rule.ti.known_bad_indicator` — fires only on a real `enrichment["threat_intel"]["matches"]`; severity from the top match reputation (`>= 0.75` → `high`, else `medium`); `technique_ids = ()` (a TI hit is not itself a technique); evidence is one `EvidenceItem(kind=ti_indicator)` carrying the matches, `as_of`, and a `threat-intel-service (via normalization-engine):<raw_event_id>` provenance. |
| Wiring | `mitre-service` + `threat-intel-service` in `Dockerfile.app` (COPY + `pip install`), `docker-compose.yml` (`detect` profile, ports 8007 / 8008), CI (installs, `mypy` trees 11 + 12, image entrypoint-import). `normalization-engine` `pyproject.toml`: `httpx` runtime dep, `respx` dev dep. `known-first-party` += the two service modules. Config: `SM_MITRE_*` / `SM_TI_*` (providers, timeouts, retries, TTLs, sweep / poll intervals, service URLs, `ti_enrichment_enabled`). |

### Integration verification

- `test_intel_models_pg.py` — the `0004` CHECK / uniqueness / global-catalog constraints.
- `test_mitre_catalog_pg.py` — a fixture-bundle import records the matrix version (technique_count 3, subtechnique_count 1), deprecated techniques are hidden from the listing, a reimport replaces the version in place, map + persist + heatmap + tenant isolation.
- `test_ti_store_pg.py` — upsert add → update the same row; a global and a tenant IOC of the same value are separate rows; enrich hit / miss / expired / malformed; list scope is global + this tenant; the sweep returns only rows that crossed into expired.
- `test_ti_poller_pg.py` — a fixture poll upserts 3, emits 3 `ti.updates`, records `ti_source` (`fixture`/`fixture`/`ok`/3); a second poll re-updates, no new rows.
- `test_ti_enrichment_chain_pg.py` (Unit 5) — a seeded **global** IOC → the real `normalization-engine` `ThreatIntelEnricher` over the real `POST /api/v1/ti/enrich` (ASGI transport) → `canonical.enrichment["threat_intel"]` populated with a reputation, `freshness == "fresh"`, and provenance → `detection-engine` `run_rules` raises `rule.ti.known_bad_indicator` at `high` with a `ti_indicator` evidence item; an unknown indicator value produces `{}` and no rule hit.

### Pre-output engineering review (Constitution §23)

- **Never fabricate threat intelligence (§3).** `normalize_indicator_value` raises `ValueError` on a malformed value; the API turns that into a 422 and the poller counts it as malformed — a bad value is never coerced into a stored indicator. `ProviderAdapter` drops a row it cannot parse (logs + metric) rather than inventing fields. `EnrichmentMatch.matched` is true only when a row is present **and** not expired. Every `ThreatIndicator` carries a `Provenance` (provider, `source_kind`, reference, `retrieved_at`); fixture data is `source_kind = FIXTURE` / `provider = "fixture"` and the fixture bundle file is self-labelled.
- **Do not claim ATT&CK coverage beyond the imported data.** `AttackMatrixVersion` stores the counts the parser actually produced and the bundle sha256. `MappingEngine` only ever returns techniques that are in the catalog; anything else is `unmapped`. No string names a "current" ATT&CK version. The repo ships no STIX bundle (`.gitignore` + ADR-024); CI and local tests use the labelled mini fixture.
- **Provider outage → serve what we have, mark it stale (TB-4).** A provider timeout / unreachable / 429-exhausted / HTTP-error → `ProviderResult(ok=False, [])`; the poller logs and skips, `ti_source.last_poll_status` records the failure, and the store keeps serving its existing indicators whose `freshness_for` ages `fresh → aging → stale → expired` on read against the TTL. Nothing is dropped, nothing is invented.
- **Deterministic reputation.** `reputation_score` is a pure function of `(confidence, tags)` — fixed base (0.35 / 0.6 / 0.85), fixed tag deltas, clamped and rounded. No RNG, no clock, no model.
- **Tenant isolation.** The catalog is global (no `tenant_id`); every `technique_mapping` and every tenant-submitted indicator carries the token's `tenant_id`, never a request field. `indicator_dedup_key` keeps a tenant IOC separate from the global one of the same value. `enrich` / `list_indicators` scope to `tenant_id IS NULL OR tenant_id = :t`. Integration tests assert a second tenant sees neither the first's mappings nor its indicators.
- **Enrichment cannot fail an event (R2).** `ThreatIntelEnricher.enrich` catches every `httpx.HTTPError` and returns `{}`; `run_enrichers` additionally traps any exception into `enrichment["_errors"]`. A TI-service outage degrades enrichment to absent, never a poison / retry.
- **Malformed input.** `mitre-service` / `threat-intel-service` consumers: an unparseable or wrong-type record → `PoisonError` → the topic DLQ; a DB write or produce failure → `TransientError` → retried by `RecordProcessor`.
- **Bounded / feature-flagged external surface.** `SM_TI_PROVIDERS` is empty by default, so no outbound provider call is made unless an operator opts in. `SM_TI_ENRICHMENT_ENABLED` is off by default. The OTX adapter reads its key from `SM_TI_OTX_KEY` env only.

### Deferred (deliberately)

- **A real ATT&CK import** — `scripts/import_attack_stix.py` is ready; an operator runs it against a pinned `enterprise-attack.json` out of band. Until then the catalog is empty and `/readyz` says so; `MappingEngine` maps nothing.
- **`ti.updates` consumers** — `mitre-service` maps `detections`; no service yet consumes `ti.updates` to re-score existing detections against newly-arrived IOCs. Phase 7+.
- **TI / MITRE as composite-score inputs** — `rule.ti.known_bad_indicator` contributes through the existing rule channel; a dedicated TI weight in `scoring.py` is not added (R8 note).
- **`detection-engine` → `mitre-service` `POST /map` call** — a raised detection's technique candidates are mapped by the `mitre-service` `detections` consumer (Unit 2), not by a synchronous call from `detection-engine`; the synchronous enrichment of a detection row with returned mappings is left to the read/API phase.
- **External-provider live verification** — the `abusech` / `otx` adapters match the documented public shapes and are unit-tested with fixtures; no live call has been made (no credentials, feature-flagged off).
- **Redis reputation cache** (R9) — reputation is computed deterministically on write; a cache is unnecessary at current scale.

### Exit criteria status

| Criterion | Status |
|---|---|
| IOC model / IP-domain-hash indicators / reputation / actors / campaigns | ✅ `sm_contracts.threatintel` + `threat_indicator` / `threat_actor` / `ti_campaign` |
| Provider adapter interface (`ThreatIntelProvider → ProviderAdapter → ExternalProvider`) | ✅ `sm_ti_service.providers` |
| Timeouts / retries / rate-limit / malformed / outage / provenance | ✅ `ProviderAdapter` + unit tests (`test_providers.py`) |
| Enrichment + provenance + confidence + freshness + expiration | ✅ `IndicatorRepository.enrich` + `ExpirySweeper` + `freshness_for` |
| Never fabricate threat intelligence | ✅ reject-not-fabricate, `Provenance` mandatory, fixtures labelled |
| MITRE technique representation + mapping + ATT&CK versioning | ✅ `sm_contracts.mitre` + `mitre-service` catalog + `AttackMatrixVersion` |
| Do not claim ATT&CK coverage beyond imported data | ✅ counts + sha from the parse; `unmapped` for anything off-catalog; no bundle ships |
| Tests: indicator validation / enrichment / provider failure / stale / duplicate / mapping / tenant isolation / provenance | ✅ unit + 5 real-PG integration files |
| Enrichment cannot fail an event | ✅ `ThreatIntelEnricher` → `{}` on any error (R2), integration-verified |
| **CI green on a clean runner** | ✅ **all four jobs — run `34366970151`** |

## Phase 5 exit report

**State: COMPLETE / CI-VERIFIED (all four jobs, run `34358654888`) against real
PostgreSQL + Redis + Redpanda + Neo4j. The detection *pipeline* is real and end-to-end;
trained models (Isolation Forest, autoencoder) and any accuracy figure are
`NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION` (ADR-024). No accuracy / F1
/ ROC-AUC / precision / recall / latency / throughput number is produced or
stored anywhere.**

### Delivered (Units 1–5)

| Area | State |
|---|---|
| `sm_contracts.detection` | `DetectionPayload` (on `detections`, `EventType.detection_raised`) — **STABLE**; `EvidenceItem` / `EvidenceKind`; `detection_dedup_key` / `detection_id_for` (deterministic, day-bucketed); DTOs `Detection` / `Anomaly` / `ThreatScore` / `SecurityAlert`; enums `Severity` / `DetectorKind` / `AnomalyMethod` / `ScoringStatus` / `DetectionStatus` / `AlertStatus` / `ThreatSubjectType`. |
| `migrations/postgres/0003` + models | `detection` / `anomaly` / `threat_score` / `security_alert` — `detection-engine`'s system of record. Enum CHECK constraints sourced from the contract enums, score-range checks, `threat_score` one-row-per-subject, alert cascades with its detection, `updated_at` triggers. |
| `packages/ml-py` (`sm_ml`) | `FEATURE_SCHEMA_VERSION` + a `FeatureSchema` per `CanonicalKind` + deterministic numpy-free `extract_features`; `Preprocessor` (versioned standardisation); the `AnomalyModel` protocol + `AnomalyScore`; `StatisticalModel` (MAD z-score, stdlib-only); `IsolationForestModel` (sklearn, `sm-ml[serving]`); `AutoencoderModel` spec + `ModelNotTrained`; `ModelRegistry` (loads artifacts from `SM_ML_MODEL_DIR`, missing dir = empty). `ml/models/*/CONTRACT.md` per §6. |
| `services/ml-inference` (ADR-013) | internal-JWT `POST /api/v1/infer/{model}` + `GET /api/v1/models`; `ModelHost` lazy-load + cache; a missing / unloadable / serving-deps-absent model → HTTP 503 `MODEL_UNAVAILABLE` (never a 500, never a fabricated score); per-model request / error / latency / load metrics. |
| `services/detection-engine` | `events.canonical` → features → per-`(tenant, kind)` rolling-window `StatisticalModel` (adaptive thresholds) → `anomaly`; optional `ml-inference` contribution, failure → `DEGRADED`; six deterministic rule detectors over a time-bounded `EventTimeline`; deterministic composite score (`WEIGHTS_VERSION`, renormalised); a `detection` (deterministic id, upsert) only above threshold or on a `medium`+ rule, every claim an `EvidenceItem`; `security_alert` at `high`/`critical`; `threat_score` upsert per subject; emits `DetectionPayload`. |
| Wiring | 3 new packages/services into `Dockerfile.app`; `ml-inference` + `detection-engine` compose services (`detect` profile, ports 8005 / 8006); CI installs + `mypy` 10 trees + image import; `mypy_path` += `sm_ml`; `sm_ml` in ruff `known-first-party`; numpy/sklearn/joblib `ignore_missing_imports`. |

### Integration verification (Unit 5)

`tests/integration/test_detection_pipeline_pg.py` (real PostgreSQL): an
auth-failure burst on `events.canonical` → `detection-engine` engine → one
`detection` row (deterministic id, `rule.auth.failed_burst`, `T1110`, evidence
with `rule_match` + `event` kinds and a `provenance` on every item); a `high`
burst opens exactly one `security_alert` and stays one detection across the whole
burst (dedup); a second tenant sees nothing. `test_detection_models_pg.py` (Unit
1): the CHECK / cascade / uniqueness constraints. 417 unit tests, ruff,
`mypy --strict` over 10 src trees, `gen_contracts --check`.

### Pre-output engineering review (Constitution §23)

- **Non-fabrication (§3).** No accuracy / F1 / ROC-AUC / precision / recall /
  latency / throughput value appears in any contract, model contract, service,
  test, or doc. `ml/models/*/CONTRACT.md` carry the literal `METRICS: NOT
  VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`. A `detection` is written only
  when a rule fired (a stated fact) or the composite score crossed a configured
  threshold; its meaning is its `evidence` JSON, and every `EvidenceItem` has a
  `provenance` (`<service>:<id>`). MITRE technique ids on a rule are named as
  *candidates* for Phase 6, not assertions.
- **Degrade, never drop (ADR-013).** `ml-inference` unreachable / 503 / timeout,
  or an inference exception → the model contribution is dropped, the composite
  score renormalises over what remains, `scoring_status = DEGRADED` is recorded,
  and a metric fires. Verified in unit + integration. The statistical detector
  needs only the standard library, so a score is always computable once the
  window has warmed.
- **Determinism.** Features are pure functions of the event (no clock, no RNG),
  clamped to the schema range. The composite score is a fixed versioned weighting.
  `detection_id_for(dedup_key, day)` is `uuid5` — a reprocess updates the row.
  The dedup key is `(tenant, rule-or-anomaly, subject)`, **not** the detector
  kind (which flips `rule → composite` when the window warms mid-burst — the bug
  the integration test caught).
- **Tenant isolation.** Every row's `tenant_id` is the event's, never a field.
  The rolling windows and the rule timeline are keyed by `tenant_id`. The FK is
  `RESTRICT`. Integration test: a second tenant's burst against the same subject
  produces zero rows for the first.
- **Bounded state.** The feature windows (`deque(maxlen=SM_DETECTION_WINDOW_SIZE)`
  per `(tenant, kind)`) and the rule timeline (time-pruned, `max_per_tenant`) are
  in-process and capped — a restart loses the warm-up and refills from the
  stream. Redis-backed shared windows are the scale path and do not change the
  contract; recorded as standing debt.
- **Malformed input.** Unparseable / not-`event.canonical` / unknown-kind record
  → `PoisonError` → `events.canonical.dlq`. A DB write or a produce failure →
  `TransientError` → retried by `RecordProcessor`.

### Deferred (deliberately)

- **`ml-training`** — dataset adapters + training pipelines + the benchmark
  harness. Until it runs, `ml-inference` serves `MODEL_UNAVAILABLE` for the
  trained models and `detection-engine` runs on the statistical detector.
- **Autoencoder training** — architecture is fixed (`AutoencoderSpec`); no
  weights (`ModelNotTrained`).
- **`features.derived` stream** — the stateful `feature-aggregator` job (windowed
  aggregates) is still a contract only (ADR-010); `detection-engine` computes
  per-event features in-process for now.
- **MITRE mapping / TI enrichment** of a detection — Phase 6. Technique ids are
  candidate labels on rule hits.
- **`detection_read` projection** in `api-gateway` — the read/API surface for
  detections is a later phase.
- **Redis-backed rolling windows** — in-process + bounded today.

### Exit criteria status

| Criterion | Status |
|---|---|
| telemetry → features → detection → anomaly score → evidence → alert | ✅ `detection-engine`, integration-verified |
| Rule-based / behavioral / statistical detection | ✅ 6 rule detectors + MAD z-score statistical detector |
| Isolation Forest | ✅ `IsolationForestModel` (sklearn) — served by `ml-inference` when an artifact exists; else `MODEL_UNAVAILABLE` → degrade |
| Autoencoder architecture where justified | ✅ `AutoencoderSpec` (network_flow / process_exec); not trained (`ModelNotTrained`), justification documented |
| Adaptive thresholds | ✅ per-`(tenant, kind)` rolling window, refit every event |
| Anomaly scoring / alert generation / detection evidence / detection lifecycle | ✅ `anomaly` / `security_alert` / `EvidenceItem` / `DetectionStatus` |
| Real preprocessing + inference interfaces | ✅ `sm_ml.Preprocessor` + `AnomalyModel` + `ml-inference` typed API |
| feature schema / model schema / version / preprocessing / inference / postprocessing / confidence / evaluation | ✅ `FeatureSchema` + `ml/models/*/CONTRACT.md` (§6) |
| Performance marked NOT VERIFIED where unrun | ✅ `METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION` everywhere |
| No fabricated accuracy / F1 / ROC-AUC / precision / recall / latency / throughput | ✅ none anywhere |
| Model loading failure / inference failure / degradation | ✅ `MODEL_UNAVAILABLE` / `TransientError` / `DEGRADED`; unit + integration |
| Alert persistence / tenant isolation | ✅ real-PostgreSQL integration tests |
| Observability: detection / anomaly / model-error / inference-duration / alert-failure counts | ✅ `sm_detection_*` + `sm_inference_*` metrics |
| **CI green on a clean runner** | ✅ **all four jobs — runs `34353986031` / `34355234014` / `34356219219` / `34357914090` / `34358654888`** |

## Phase 4 exit report

**State: COMPLETE / CI-VERIFIED (all four jobs, run `34350607501`) against real
Neo4j 5 Community + real Redpanda. GDS pathfinding/centrality and the
operational-graph pruning job are deferred to their consuming phase.**

### Delivered (Units 1–4)

| Area | State |
|---|---|
| `sm_common.graph` | `Graph` async Neo4j driver wrapper (connectivity probe, per-query timeout, `GraphUnavailableError`, parameter-only `run_read` / `run_write`); `apply_pending` migration runner + `split_statements`. |
| `sm_contracts.graph` | the label / relationship **allowlist** (`GRAPH_NODE_KEY` 13 labels, `GRAPH_NODE_LABELS`, `GRAPH_REL_TYPES` 15 types), `normalize_label`, `graph_node_uid`; `GraphEventPayload` + `GraphMutationOutcome` + `EventType.graph_event`. `GraphCommandPayload` promoted **STABLE**. Contract test pins the allowlist to `data-model.md`. |
| `migrations/neo4j/0001_schema.cypher` | per-tenant `uid` UNIQUE constraint per label + `_GraphCommand` / `_GraphMigration` ledgers + tenant-key range indexes + temporal indexes + `Host`/`Domain`/`Identity` full-text. Runner `scripts/graph_migrate.py` (`--status`); `make migrate` applies it; CI `integration` runs it against a real `neo4j:5-community` service. |
| `services/graph-service` | **the only write path into Neo4j.** Consumes `graph.commands` (group `graph-writer`) via `RecordProcessor`; `GraphWriter.apply` — parameterized MERGE (label allowlist-checked, off-list → DLQ), idempotent by `command_id` (`_GraphCommand` ledger), out-of-order safe (`_watermark`), tenant invariants by construction (synthetic `uid`), missing endpoint nodes created thin, no duplicate relationships, `PRUNE` not-yet-implemented → DLQ. `GraphEngine.handle` maps Neo4j outage → `TransientError` and emits `graph.events`. |
| `services/graph-service` query API | `GraphRepository` (`entity` / `neighbors` / `attack_path`) + `GET /api/v1/graph/{entity,neighbors,paths}`. Parameterized only; **tenant scope from the verified internal JWT, never a request field**; depth clamped to `SM_NEO4J_TRAVERSAL_MAX_DEPTH`, row-capped `SM_NEO4J_QUERY_MAX_ROWS`, `_`/`uid` props stripped. `deps.get_principal` is the mesh's first `verify_internal_token` verifier. |
| `AppSettings` | `SM_NEO4J_PASSWORD` production fail-fast guard; `SM_NEO4J_QUERY_MAX_ROWS`, `SM_NEO4J_TRAVERSAL_MAX_DEPTH`. |
| `deploy/docker` | `neo4j` healthcheck (`graph` profile); `graph-service` service (`graph` profile, `depends_on` neo4j healthy, port 8004); one image builds all 6 services. CI: 7th mypy tree, install + import checks, Neo4j service + schema step. |

### End-to-end verification (Unit 4)

`tests/integration/test_graph_pipeline_e2e.py` — real Redpanda + real Neo4j:
a canonical `auth` event on `events.canonical` → `stream-processor` engine →
`graph.commands` → `graph-service` engine → Neo4j. The graph then has
`(:Identity {identity_id:'e2e-alice'})-[:AUTHENTICATED_TO]->(:Host {host_id:'e2e-web01'})`;
`GraphRepository.entity` / `neighbors` / `attack_path` return it; `graph.events`
carries `outcome: APPLIED`. 349 unit tests, ruff, `mypy --strict` over 7 src
trees, 91 integration tests all pass.

### Pre-output engineering review (Constitution §23)

- **Cypher injection.** The only interpolation anywhere is a node label / rel
  type, always after `normalize_label` + a membership check against a frozen
  `frozenset` whose members are compile-time string literals, and it is
  back-tick-quoted. The query-API depth is `max(1, min(int(d), cap))`. Every
  other value is a bound parameter. `test_graph_model.py` fails the build if the
  allowlist drifts from `data-model.md`; `test_repository.py` / `test_writer.py`
  assert the caller's key value never appears in the query text.
- **Tenant isolation.** Node identity is `uid = "<tenant>:<key>"` (UNIQUE), so a
  MERGE_EDGE cannot join two tenants; every read filters
  `all(x IN nodes(p) WHERE x.tenant_id = $tenant)` and the tenant comes from the
  JWT. `test_graph_service_neo4j.py::test_queries_never_cross_tenants` and
  `::test_relationships_never_cross_tenants` prove it against real Neo4j.
- **Idempotency vs. atomicity.** The ledger row is written *after* the
  (idempotent) MERGE, so a crash between them re-runs the MERGE — never a
  command marked done but not applied. Cost: a redelivered STALE/DUPLICATE
  re-runs one idempotent MERGE. Accepted and documented.
- **Auto-commit, single statement.** `graph-writer` applies one command as one
  statement, so auto-commit is correct; a multi-statement transaction would buy
  nothing here. The migration runner is the same.
- **`_watermark` is an internal prop.** Stripped from every query response;
  never part of a key. Node/edge `first_seen` still widens on an out-of-order
  event so temporal-range queries stay correct.
- **Community-edition limits.** No composite `NODE KEY`, no read-only role, one
  database. The synthetic `uid` covers uniqueness; the read/write split is
  enforced in code (writes only via `graph-service`); `graph` property `'op'`/`'kg'`
  is written but the operational/knowledge split by database waits for Enterprise
  (U-003). Documented in ADR-007 and `data-model.md`.

### Deferred (deliberately)

- **GDS** (pathfinding at scale, centrality, community detection) — Phase 5+/
  graph-ML, its consuming phase.
- **Operational-graph pruning job** (retention-window sweep, promote-to-knowledge
  on confirmed chains) — needs the retention config + a scheduler; `PRUNE`
  commands are dead-lettered with a clear message until then.
- **`:Detection` / `:AttackChain` / MITRE nodes** — produced by `detection-engine`
  (Phase 5+); the labels are already on the allowlist.
- **Enterprise features** (multi-database op/kg split, native read-only role,
  clustering) — open licensing question (ADR-007), does not block development.

### Exit criteria status

| Criterion | Status |
|---|---|
| Neo4j integration (driver, config, health) | ✅ `sm_common.graph`, `probe_check("neo4j", …)` |
| Graph repository + node/relationship models | ✅ `GraphWriter` + `GraphRepository`; models = `data-model.md` (locked) |
| Constraints + indexes | ✅ `migrations/neo4j/0001_schema.cypher`, runner, CI applies it |
| Graph update consumer (normalized event → command → mutation) | ✅ `stream-processor` → `graph.commands` → `graph-service` → Neo4j, e2e verified |
| Duplicates / out-of-order / missing nodes / tx failure / Neo4j down / retry | ✅ ledger / `_watermark` / thin-create / `TransientError`; integration tests |
| Never blindly create duplicate relationships | ✅ MERGE on endpoints only; `test_repeated_edge_commands_never_duplicate_the_relationship` |
| All Cypher parameterized; no untrusted interpolation | ✅ allowlist + bound params only; §23 above; contract + unit tests |
| Controlled graph query interfaces | ✅ `GraphRepository` + 3 internal endpoints; no raw-Cypher path |
| Temporal graph representation | ✅ `observed_at` / `first_seen` / `last_seen` on every node+edge; range indexes; `attack_path` |
| Attack-path traversal | ✅ `GraphRepository.attack_path` (`shortestPath`, depth-bounded), real-Neo4j test |
| Tenant isolation | ✅ synthetic `uid` + path filter + JWT tenant; real-Neo4j cross-tenant tests |
| Real Neo4j integration tests | ✅ 20 (`test_graph_schema_neo4j` 6, `test_graph_service_neo4j` 10, `test_graph_pipeline_e2e` 1, + query cases) |
| **CI green on a clean runner** | ✅ **all four jobs — runs `34346140544` / `34348143536` / `34349655012` / `34350607501`** |

## Phase 3 exit report

**State: IMPLEMENTED / INTEGRATION VERIFIED (real Redpanda) for the Kafka
backbone; Units 1–3 CI-green; Unit 4 = this report + decisions. Flink not
implemented (deferred per ADR-010).**

### Delivered (Units 1–4)

| Area | State |
|---|---|
| `sm_contracts.topics` | the definitive 12-topic catalog (`TOPICS`, `TopicSpec`), `EVENT_TYPE_TOPIC` / `topic_for_event_type`, `dlq_topic` / `replay_group`, `EVENT_TYPE_VERSION` + the `.v2` breaking-change policy. STABLE. |
| `sm_contracts.graph` | `GraphCommandPayload` / `GraphOp` / `GraphEndpoint` / `graph_command_id` (CONTRACTS.md §5). STABLE target — consumer is Phase 4. |
| `sm_common.bus` | `EventBusProducer` (idempotent, `acks=all`, `flush` on stop, send-error metric), `EventBusConsumer` (manual commit, **rewind-on-failure**, graceful shutdown, `seek_by_timestamp`, lag/records metrics, backpressure bound), `RecordProcessor` (retry→DLQ), `dlq_payload`, `admin.ensure_topics` (create + grow). |
| `services/normalization-engine` | refactored onto `RecordProcessor`; its bespoke DLQ/retry loop removed; duplicate metrics dropped. |
| `services/stream-processor` | new — `graph-update-emitter` job (`events.canonical` → `graph.commands`), stateless, health/metrics. |
| `scripts/` | `provision_topics.py` (+ `--list`), `replay.py` (dry-run default, `*-replay` group enforced). |
| `deploy/docker` | `topics-init` one-shot, `stream-processor` service (`bus` profile), one image builds all 5 services. |
| `docs/architecture/observability.md` | new — metric catalog + alerts. |
| ADR-010 | revised: engine-independent contracts stand; **plain-Python for stateless jobs**; stateful jobs pick an engine (Bytewax front-runner, Flink if state demands) at their consuming phase. **U-001 / U-002 RESOLVED.** |

### Not implemented (deliberately)

- **Flink / any cluster stream engine** — no JDK 11+ locally (ADR-001); no
  stateful job's consuming phase has arrived. `feature-aggregator`,
  `attack-chain-correlator`, `lateral-movement`, `temporal-stitcher` are
  contracts only (event-model.md §7).
- **Schema registry / Avro** (U-004) — still JSON; the envelope survives the
  switch when volume justifies it.
- **`graph.commands` has no consumer** — `graph-writer` / Neo4j is Phase 4.
- OTLP collector / scraped Prometheus — opt-in, not wired locally.

### Exit criteria status

| Criterion | Status |
|---|---|
| Topic strategy: partitions / keys / retention / ordering / groups / versioned types | ✅ `sm_contracts.topics` + event-model.md §2/§3 |
| Producer / consumer / consumer groups / serialization / schema validation | ✅ `sm_common.bus` + `RecordProcessor` |
| At-least-once / idempotent consumers / duplicates / retries / poison / restart / offsets | ✅ verified (`test_bus_kafka.py`) |
| DLQ topics + handling | ✅ `dlq_payload` → `<topic>.dlq`, consumer + producer sides (event-model.md §5) |
| Replay | ✅ `seek_by_timestamp` + `scripts/replay.py` |
| Graceful shutdown / backpressure / observability | ✅ + `observability.md` |
| Kafka = transport, Flink = stream processing, Redis = cache — no duplication | ✅ ADR-008/009/010; roles documented |
| Flink "only where Phase 0 established it as necessary" | ✅ nowhere yet — deferred, decision recorded |
| Real Kafka integration tests | ✅ 13 against Redpanda (bus 9, norm 2, stream 2) |
| **CI green on a clean runner** | ✅ **all four jobs — run `34342866073`** |

## Phase 4, Unit 1 — Neo4j foundation (DONE — local + unit verified)

- `sm_common.graph.Graph` — one async `neo4j` driver per process. `start()` /
  `ping()` verify connectivity (`ServiceUnavailable` / `OSError` →
  `GraphUnavailableError`, which the caller turns into a 503 / `TransientError`);
  `run_read` / `run_write` take a Cypher string + a parameter dict and run it
  auto-commit with `default_access_mode` READ / WRITE and the configured
  per-query timeout (`SM_NEO4J_QUERY_TIMEOUT_MS`, default 10 s — a slow query
  raises, never hangs). A real `Neo4jError` (constraint violation etc.)
  propagates unwrapped so the writer can decide DLQ vs. retry.
- `sm_contracts.graph` — the Neo4j **label / relationship allowlist**
  (`GRAPH_NODE_KEY` 13 labels + key property, `GRAPH_NODE_LABELS`,
  `GRAPH_REL_TYPES` 15 types), `normalize_label(":Host" → "Host")`,
  `graph_node_uid(tenant_id, key)` → `"<tenant>:<key>"`. Cypher cannot
  parameterize a label or relationship type, so `graph-service` (Unit 2) checks
  every command's label against these sets before building Cypher; anything else
  is dead-lettered. `packages/contracts-py/tests/test_graph_model.py` pins the
  allowlist to `data-model.md` (the only extra beyond the canonical set is
  `ACCESSED`, used by the stream-processor file-access mapper).
- `migrations/neo4j/0001_schema.cypher` + `sm_common.graph.apply_pending`
  (runner) + `scripts/graph_migrate.py` (CLI, `--status`). Versioned `.cypher`
  files applied in filename order, each recorded as a `:_GraphMigration`
  node → re-running is a no-op. 0001 creates: a UNIQUE constraint on the
  synthetic per-tenant `uid` for every node label (Community has no composite
  NODE KEY — data-model.md permits "a synthetic key"), a `_GraphCommand.command_id`
  UNIQUE constraint (idempotency ledger for Unit 2), tenant-scoped
  `(tenant_id, <key>)` range indexes, `last_seen` / relationship `observed_at`
  range indexes, and the `Host.hostname` / `Domain.fqdn` / `Identity.name`
  full-text indexes for hunting.
- `AppSettings` — `SM_NEO4J_PASSWORD` is now a production fail-fast guard (like
  `SM_PG_PASSWORD`); the stale "unused until Phase 2/3" comment is corrected.
- Wiring: `neo4j` gets a compose healthcheck under the `graph` profile;
  `make migrate` now also runs the Neo4j schema; CI `integration` job adds a
  `neo4j:5-community` service + an "Apply Neo4j schema" step; the `image` job's
  entrypoint-import check covers `sm_common.graph` + `neo4j`; the two prod-guard
  image steps carry `SM_NEO4J_PASSWORD`. `.env.example` neo4j block corrected
  (dropped the non-existent `SM_NEO4J_MAX_POOL_SIZE`).
- Tests: `packages/common-py/tests/test_graph_driver.py` (12 — fake driver:
  param / timeout / access-mode pass-through, outage wrapping, `Neo4jError`
  propagation, statement splitter), `test_graph_model.py` (8),
  `test_config.py` (+2). `tests/integration/test_graph_schema_neo4j.py` (6,
  marked `integration`, real Neo4j via the `graph` fixture): migration creates
  constraints + indexes, idempotent re-run, apply-from-bare-schema, `uid`
  uniqueness enforced, parameter values never executed as Cypher, slow query
  hits the timeout. Verified locally against Neo4j 5 Community **and CI-green**
  (run `34346140544`).

## Phase 2 exit report

**State: IMPLEMENTED / INTEGRATION VERIFIED (local + compose + live) / §23
REVIEWED. CI-VERIFIED pending a GitHub remote.**

### Delivered (Units 1–4 + review)

| Area | State |
|---|---|
| `sm_contracts.telemetry` | the 5 sensor payloads + `CanonicalEventPayload` / `EntityRef`; IP-validated, free-text bounded, case-normalized, cross-field rules, lineage. Registered in `EVENT_PAYLOAD_REGISTRY` + `SCHEMA_MODELS`. `make_partition_key` (shared derivation). STABLE target. |
| `sm_common.bus` | `EventBusProducer` (aiokafka, idempotent, `acks=all`), `EventBusConsumer` (manual commit after side effect), `dlq_payload` (event-model.md §5 shape). |
| `sm_common.security.sensor_auth` | `SensorAuth` / `SensorIdentity` — `<sensor_id>.<secret>`, Argon2id, `dummy_verify` for unknown, one generic `Unauthenticated`, throttled `last_seen_at`. |
| `services/ingestion-gateway` | `POST /api/v1/ingest/{source_type}` + `/batch`, per-sensor auth, envelope built server-side (tenant from identity only), fail-closed rate limiter, `X-Sensor-Event-Id` dedup, Kafka `RawEventSink` / `DeadLetterSink` (logging stopgap when the bus is off), health/metrics. |
| `services/normalization-engine` | consumes `telemetry.raw`, deterministic per-source mapping → `CanonicalEventPayload`, produces `events.canonical` with a deterministic `event_id`; poison → `telemetry.raw.dlq`; `enrich/` is a stub protocol (no providers). Pure stream processor + health/metrics. |
| `deploy/docker` | one `Dockerfile.app` builds all four services; compose `ingestion-gateway` (default) + `normalization-engine` (`bus` profile) + `redpanda` (dual listener). **Compose stack run: 6 containers healthy; live end-to-end passed.** |
| `.github/workflows/ci.yml` | `static` / `unit` / `integration` (+ runner-hosted redpanda) / `image` (builds all four services, asserts each imports, + prod-config guards). **CI-VERIFIED** — run `34333269219`, all four jobs green on `ubuntu-latest`. |
| GitHub | `github.com/gaurav685/sentinelmesh` (private). Remote `origin`; branch `main`. |

### Pre-output engineering review (Constitution §23)

Three defects in code that had only run locally, all fixed with a regression
test — see "Pre-output engineering review (Constitution §23) — Phase 2" below:
deterministic canonical `event_id` (idempotency under redelivery); the dedup
mark freed on a 4xx (corrected retry not dropped); empty DNS answer rejected at
the contract boundary. Commit `862eb9e`. Six-role sign-off recorded there.

### First-run CI defect

First push to a clean runner: the `unit` job failed 4 config tests. Root cause —
the workflow set `SM_ENV` / `SM_SERVICE_NAME` / `SM_PG_PASSWORD` /
`SM_INTERNAL_JWT_SIGNING_KEY` / `SM_OIDC_CLIENT_SECRET` as global job env, and
`pydantic-settings` reads OS env regardless of `_env_file=None`, so those leaked
into every `AppSettings` a unit test built (`test_defaults_local` saw `env=ci`;
`test_service_name_required` / `test_production_requires_secrets` stopped
raising; `api-gateway` `test_meta` saw `environment=ci`). Fix: a repo-root
`conftest.py` autouse fixture strips `SM_*` for every non-integration test (unit
tests are hermetic now, regardless of the ambient environment — a developer with
`SM_ENV` exported hit the same latent bug); the `SM_*` block removed from the
workflow's global `env:`. Commit `8064fd9`. Second run: all four jobs green.

### Not verified (the whole list)

- Enrichment: Geo-IP, hostname resolution, identity stitching (`identity_link`),
  threat-intel tagging — protocol only, zero providers. Later units/phases.
- `events.canonical` has no consumer yet (Phase 3 `graph` / `detection`).
- Topic pre-creation with real partition counts (event-model.md) — a deploy-time
  task, auto-created locally / in CI.
- Per-sensor rate quota (currently per-IP).
- Any metric scraped from a real Prometheus; any span at a collector.

### Exit criteria status

| Criterion | Status |
|---|---|
| Every requirement (R1, R2) has a service + code + tests | ✅ |
| Full pipeline works end to end | ✅ live through the compose stack |
| Contracts registered + schema-generated | ✅ |
| `mypy --strict` + `ruff` clean | ✅ (106 files) |
| Unit + integration suites green | ✅ 268 + 63 |
| §23 review done | ✅ 3 defects fixed |
| **CI green on a clean runner** | ✅ **run `34333269219` — all four jobs** |

**Phase 2 is COMPLETE.**

## Phase 1 exit report

### Delivered (Units 1–6 + review)

| Area | State |
|---|---|
| `packages/contracts-py` | envelope, error contract, Phase-1 entities + APIs, enums; JSON-Schema codegen. STABLE. |
| `packages/common-py` | config + production guards, structured logging + redaction, request/correlation IDs, `SmError`, Argon2id, internal JWT, OIDC client, async Postgres + Redis clients, health/metrics/tracing, audit hash chain + `AuditWriter`, FastAPI middleware (context, security headers, body limit, **rate limit**, CORS builder), `client_ip` proxy resolution. |
| `migrations/postgres` | 8 control-plane tables + RBAC seed; `updated_at` and append-only audit triggers; reversible. |
| `services/api-gateway` | local + OIDC login, Redis sessions + CSRF, deny-by-default RBAC, tenant-scoped repositories, audited admin routes, `/healthz` `/readyz` `/health/deps` `/api/v1/meta` `/metrics`, full hardening stack incl. per-caller rate limiting. |
| `deploy/docker` | compose stack + non-root `Dockerfile.app` + Keycloak dev realm + Prometheus config. **Authored, never run.** |
| `.github/workflows/ci.yml` | static / unit / integration (service containers) / image jobs; `SM_REQUIRE_INTEGRATION=1` makes a skipped integration test a failure. **Never run.** |

### Pre-output engineering review (Constitution §23)

Seven defects found in never-run code, all fixed with regression tests:

| # | Defect | Commit |
|---|---|---|
| 1 | Login lockout double-incremented `failed_login_count` (proven red/green) | `5f29957` |
| 2 | An authorization denial became a 500 when the audit write failed | `5f29957` |
| 3 | Client IP taken from a spoofable source (`request.client.host`) | `6e5becc` |
| 4 | 413 body carried a zeroed `request_id` | `6e5becc` |
| 5 | `BodySizeLimitMiddleware` could emit a duplicate `http.response.start` | `6e5becc` |
| 6 | Audit advisory lock on `hashtext` (int4) — widened to int8 | `6e5becc` |
| 7 | Rate limiting specified but never wired | `901d9c1` |

Six-role sign-off (each role reviewed the Phase-1 surface):

- **Principal Engineer** — service boundaries hold; `api-gateway` owns only its
  control-plane tables and the read projections; no service imports another's
  internals; the dependency graph is acyclic. No concern.
- **Security Engineer** — deny-by-default confirmed; identity/tenant/role never
  taken from the request; cross-tenant probes return `not_found`; login has no
  enumeration or timing oracle; parameterized SQL only; CSRF double-submit;
  rate limiting in front of auth. Open items: no account-recovery flow (out of
  Phase-1 scope), and the audit chain's tamper-*detection* has no automated
  *verifier job* yet (recorded as a limitation).
- **SRE** — `readyz` degrades correctly; the limiter and the audit write both
  fail open with a metric; graceful shutdown drains clients. Concern: the
  `require_permission` audit opens a transaction per 403 — acceptable now that
  the limiter caps a probing flood, revisit if authz-denial volume is high.
- **Database Engineer** — every constraint has an integration test (skipped);
  migrations are reversible; the advisory lock serializes audit appends per
  tenant. The `upgrade/downgrade/upgrade` cycle is asserted only in CI, which
  has not run.
- **ML Engineer** — N/A for Phase 1.
- **Frontend Engineer** — the API returns only `sm_contracts` models; the error
  contract, CSRF header and cursor pagination are stable; `contracts-ts` schema
  is generated. No frontend code yet (Phase 4).

### Not verified (the whole list)

- The 49 integration tests: migrations against a real database and the
  reversibility cycle; seed content; `updated_at` and append-only triggers;
  the per-tenant advisory lock under concurrency; every schema constraint; the
  SQL repositories' tenant predicate, soft-delete and pagination; the Redis
  session TTL / absolute deadline; the rate-limit window TTL and rollover.
- The CI workflow: no job has run.
- `docker compose config`, any image build, any container start.
- A real OIDC round-trip against Keycloak.
- Any metric scraped from a running Prometheus; any span at a collector.

**To clear it:** install Docker Desktop and run `make up` then
`make test-integration`, **or** push to GitHub (`bash scripts/push_and_watch.sh`
after `gh auth login`) and let the `integration` and `image` jobs run.

## Architecture lock status

**LOCKED** (2026-09-08).

`LOCKED` means: the architecture documentation, decisions, and contracts satisfy
the Phase-0 lock criteria and contain no unresolved critical contradiction. It
does **not** mean any of the following (Engineering Constitution §3): the system
is implemented, deployed, integrated, benchmarked, security-audited, or that any
ML performance is validated. No such claim exists anywhere in this repository.

### Lock criteria checklist

| Criterion | State |
|---|---|
| All 38 requirements analyzed | DONE (`REQUIREMENTS_TRACEABILITY.md`) |
| All 38 requirements mapped | DONE |
| System boundaries defined | DONE (`architecture/overview.md`) |
| Trust boundaries defined | DONE (TB-1..TB-7) |
| Security boundaries defined | DONE (`architecture/security-model.md`) |
| Service boundaries defined | DONE (`architecture/service-catalog.md`, 18 logical services + 3 shared packages + frontend) |
| Service dependency graph defined | DONE (acyclic, documented) |
| Synchronous flows defined | DONE (`overview.md §5`) |
| Asynchronous flows defined | DONE (`overview.md §6`, `event-model.md`) |
| Telemetry flow defined | DONE |
| Event flow defined | DONE (`event-model.md`) |
| Graph flow defined | DONE (`data-model.md`, ADR-011) |
| Detection flow defined | DONE |
| Threat-intelligence flow defined | DONE |
| ML/AI flow defined | DONE (ADR-012..015, `CONTRACTS.md §6–7`) |
| Frontend flow defined | DONE (`CONTRACTS.md §8`) |
| Simulation flow defined | DONE |
| Reporting flow defined | DONE |
| Observability architecture defined | DONE (ADR-020) |
| Deployment architecture defined | DONE (`architecture/deployment.md`) |
| PostgreSQL model defined | DONE (Phase-1 tables in full; later tables listed, per-phase migrations pending) |
| Neo4j model defined | DONE (canonical labels/edges/invariants) |
| Redis usage defined | DONE (ADR-009 namespace table) |
| Kafka architecture defined | DONE (`event-model.md §3`) |
| Flink responsibilities defined | DONE (`event-model.md §7`) — engine choice has open questions U-001/U-002 (non-blocking) |
| Event contracts defined | DONE — canonical `EventEnvelope` **implemented + validated** (`sm_contracts.events`); payloads DRAFT per phase |
| API boundaries defined | DONE — `CONTRACTS.md §1`; Phase-1 request/response models **implemented** (`sm_contracts.api`); later endpoints land per phase |
| ML contracts defined | DONE (template `CONTRACTS.md §6`; per-model contracts land in P5) |
| Security architecture defined | DONE |
| Failure model defined | DONE (`architecture/failure-model.md`) |
| Repository structure defined | DONE (`architecture/repository.md` + skeleton created) |
| Technology decisions documented | DONE (`ARCHITECTURE_DECISIONS.md`, ADR-001..024) |
| Architecture decisions documented | DONE |
| Contracts documented + core implemented | DONE — `packages/contracts-py` implements the envelope, canonical error contract, Phase-1 entity + API models; 19 tests pass; `mypy --strict` clean; JSON Schema generated |
| Requirements traceability documented | DONE |
| Implementation state updated | DONE (this file) |
| No unresolved critical architectural contradiction | DONE — consistency-review pass completed; see `architecture/consistency-review.md` |

### Lock rationale

The three items that held lock in the prior revision are closed:

1. **Contracts materialized.** `packages/contracts-py` now contains executable,
   type-checked, tested Pydantic v2 models for the envelope, error contract, and
   Phase-1 entities/APIs. `scripts/gen_contracts.py` emits JSON Schema
   (`packages/contracts-ts/schemas/`) with a `--check` CI mode.
2. **`CLAUDE.md` reviewed** against the architecture docs — no contradiction
   (`architecture/consistency-review.md`).
3. **Consistency-review pass done** — two doc inconsistencies found and fixed
   (service count 21→18; `identity_link` ownership); recorded in
   `architecture/consistency-review.md`.

## Completed files (Phase 0)

**Docs / config (created):**
`README.md`, `.gitignore`, `.env.example`, `pyproject.toml`, `CLAUDE.md`,
`docs/ARCHITECTURE_DECISIONS.md`, `docs/CONTRACTS.md`,
`docs/REQUIREMENTS_TRACEABILITY.md`, `docs/IMPLEMENTATION_STATE.md`,
`docs/architecture/{repository,overview,service-catalog,data-model,event-model,security-model,failure-model,deployment,consistency-review}.md`,
monorepo skeleton (50 dirs; 18 `services/`, `packages/`, `frontend/web/`, `ml/`,
`deploy/`, `migrations/`, `tests/`, `scripts/`).

**`packages/contracts-py` (created + verified):**
`pyproject.toml`, `README.md`,
`src/sm_contracts/{__init__,version,common,enums,errors,events,jsonschema}.py`,
`src/sm_contracts/entities/{__init__,tenant,user,rbac,sensor,audit}.py`,
`src/sm_contracts/api/{__init__,auth,users,health,pagination}.py`,
`tests/{test_envelope,test_errors,test_entities}.py`.

**`packages/contracts-ts` (created):**
`package.json`, `README.md`, `schemas/*.json` (22 generated JSON Schema files).

**Tooling (created):** `scripts/gen_contracts.py`.

**Modified in Phase 0 close:** `pyproject.toml` (ruff line-length 120,
`known-first-party`, `scripts/**` ignores; dropped `disallow_any_explicit` with
rationale), `.gitignore` (generated TS), `docs/IMPLEMENTATION_STATE.md`,
`docs/CONTRACTS.md` (change log), `docs/architecture/service-catalog.md`
(`identity_link` fix).

## Completed files (Phase 1, Unit 1)

**`packages/common-py` (created + verified):**
`pyproject.toml`, `README.md`,
`src/sm_common/{__init__,config,logging,redaction,context,ids,clock,errors}.py`,
`src/sm_common/security/{__init__,passwords,jwt_internal}.py`,
`src/sm_common/observability/{__init__,health}.py`,
`src/sm_common/fastapi/{__init__,middleware,exception_handlers,hardening}.py`,
`tests/{conftest,test_config,test_ids,test_redaction,test_passwords,test_jwt_internal,test_fastapi,test_health,test_errors}.py`.

**Modified:** `pyproject.toml` (pytest `--import-mode=importlib` + `asyncio_mode`;
`**/errors.py` N818 ignore).

## Completed files (Phase 1, Unit 2)

**`packages/common-py` (created):**
`src/sm_common/db/{__init__,engine,session}.py`,
`src/sm_common/cache/{__init__,redis}.py`,
`src/sm_common/audit/{__init__,hashing}.py`,
`src/sm_common/observability/{metrics,tracing}.py`,
`src/sm_common/security/oidc.py`,
`tests/{test_audit_hashing,test_infra_clients,test_oidc}.py`.

**Modified:** `src/sm_common/observability/{__init__,health}.py`
(`probe_check` + `Pingable`), `src/sm_common/security/__init__.py` (OIDC exports),
`packages/common-py/pyproject.toml` (infra deps).

## Completed files (Phase 1, Unit 3)

**Created:** `packages/common-py/src/sm_common/db/{base,models}.py`,
`packages/common-py/src/sm_common/audit/writer.py`,
`migrations/postgres/{alembic.ini,env.py,script.py.mako}`,
`migrations/postgres/versions/{0001_initial.py,0002_seed_rbac.py}`,
`packages/common-py/tests/{test_models,test_audit_writer}.py`,
`tests/contract/test_migrations_offline.py`.

**Modified:** `packages/common-py/src/sm_common/db/__init__.py` (model exports),
`packages/common-py/src/sm_common/audit/__init__.py` (`AuditWriter` export),
`packages/common-py/README.md`.

## Completed files (Phase 1, Unit 4)

**Created:** `services/api-gateway/{pyproject.toml,README.md}`,
`src/sm_api_gateway/{__init__,__main__,version,app,deps,mappers}.py`,
`src/sm_api_gateway/security/{__init__,principal,session,cookies,login}.py`,
`src/sm_api_gateway/repositories/{__init__,protocols,sql}.py`,
`src/sm_api_gateway/routes/{__init__,health,auth,admin}.py`,
`services/api-gateway/tests/{conftest,test_health,test_auth_login,test_authz,test_tenant_isolation}.py`.

**Modified:** `packages/common-py/src/sm_common/config.py` (session cookie names,
idle/absolute session lifetimes, OIDC state TTL, login lockout settings),
`.env.example` (7 new keys), `pyproject.toml` (ruff `flake8-bugbear
extend-immutable-calls` for the FastAPI dependency idiom, `sm_api_gateway`
first-party).

## Verification performed (Phase 1, Unit 4 — api-gateway)

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest packages services tests -q` | **143 passed** (41 new) |
| Type check | `python -m mypy --strict --python-version 3.11` over all three packages | **Success: no issues found in 66 source files** |
| Lint | `python -m ruff check packages services tests migrations` | **All checks passed** |
| Contract schema | `python scripts/gen_contracts.py --check` | up to date |

Covered by tests: login success (cookies + CSRF header + permissions, no
password echoed); failure counter reset; wrong password / unknown user /
unknown tenant returning byte-identical generic errors; lockout at the
threshold; suspended tenant; non-active user; federated-only account;
invalid-payload and unknown-field rejection through the canonical error
contract; no session / unknown session / missing CSRF / wrong CSRF; missing
permission denied **and audited**; granted permission allowed; role revocation
taking effect on the next request; deactivated-user session dropped; invalid
cursor and over-cap limit rejected; liveness unaffected by a dead dependency;
readiness returning 503 with the failing dependency named; `/health/deps`
gated on `ops:read`; and cross-tenant isolation on user list, user create, role
grant and `/me`, with `not_found` (never `forbidden`) for another tenant's user.

**Not verified (Phase 1, Unit 4):** nothing has run against a real Postgres,
Redis or OIDC provider. The SQL repositories, the Redis session store and the
OIDC client are exercised only through in-memory fakes. Docker is being
installed; integration tests land in Unit 5.

## Completed files (Phase 1, Unit 5)

**Created:** `deploy/docker/{docker-compose.yml,Dockerfile.app,README.md}`,
`deploy/docker/keycloak/realm-sentinelmesh.json`,
`deploy/prometheus/prometheus.yml`, `.dockerignore`, `Makefile`,
`services/api-gateway/src/sm_api_gateway/routes/metrics.py`,
`tests/contract/test_deploy_local_config.py`,
`tests/integration/{conftest,test_migrations_pg,test_audit_writer_pg,test_models_constraints_pg,test_repositories_pg,test_session_store_redis}.py`.

**Modified:** `services/api-gateway/src/sm_api_gateway/{app,routes/__init__}.py`
(wire the metrics router). Dev dependency added: `pyyaml` (offline compose
checks).

## Verification performed (Phase 1, Unit 5 — local stack)

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest packages services tests -q` | **158 passed, 49 skipped** |
| Deployment config (offline) | `python -m pytest tests/contract/test_deploy_local_config.py -q` | **15 passed** |
| Type check | `python -m mypy --strict --python-version 3.11` over all three packages | **Success: no issues found in 67 source files** |
| Lint | `python -m ruff check packages services tests migrations scripts` | **All checks passed** |

The 15 offline checks assert: compose parses; core services carry no profile and
optional ones carry theirs; **no `localhost`/`127.0.0.1` in any container
environment**; per-service `SM_SERVICE_NAME`; healthchecks on the stateful
services; `app` gated on both dependencies healthy **and** `migrate` completing
successfully; `migrate` gated on postgres and `restart: "no"`;
`${SM_PG_PASSWORD:?...}` fail-fast; declared volumes; the Dockerfile being
multi-stage, non-root (`USER 10001`), health-checked, with no compiler in the
runtime stage; `.dockerignore` excluding `.env`/`.venv`/`.git`; the Prometheus
target matching the app's real port and metrics path; and the Keycloak client
being confidential with PKCE `S256`, the password grant disabled, and exact
callback redirect URIs.

**Not verified (Phase 1, Unit 5) — the important part:** `docker compose config`
has not been run, no image has been built, no container has been started, and
**all 49 integration tests are skipped**. Specifically still unproven at
runtime: the migrations applying to a real database and the
`upgrade -> downgrade -> upgrade` cycle; the seed content; the `updated_at` and
append-only triggers; the per-tenant advisory lock preventing a forked audit
chain under concurrency; every schema constraint; the SQL repositories' tenant
predicate, soft-delete filter, cursor pagination and permissions join; the Redis
session TTL and absolute-deadline behaviour; the OIDC flow against a real
provider; and the `/metrics` endpoint being scraped.

## Completed files (Phase 1, Unit 6 — partial)

**Created:** `.github/workflows/ci.yml`, `tests/contract/test_ci_config.py`.

**Modified:** `tests/integration/conftest.py` (`SM_REQUIRE_INTEGRATION` turns an
unreachable dependency into a failure instead of a skip), `README.md` (rewritten:
real status, real setup commands, explicit honesty note).

## Verification performed (Phase 1, Unit 6 — partial)

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest packages services tests -q` | **184 passed, 49 skipped** |
| CI config (offline) | `python -m pytest tests/contract/test_ci_config.py -q` | **14 passed** |
| Type check | `python -m mypy --strict --python-version 3.11` over all three packages | **Success: no issues found in 68 source files** |
| Lint | `python -m ruff check packages services tests migrations scripts` | **All checks passed** |
| Skip-guard behaves | same module with and without `SM_REQUIRE_INTEGRATION=1` | **11 skipped** vs **11 errors** — the guard works |

The CI workflow defines four jobs: `static` (ruff + `mypy --strict`), `unit`
(`-m "not integration"` plus `gen_contracts.py --check`), `integration`
(postgres:16 + redis:7 service containers, applies migrations, runs the 49
tests with `SM_REQUIRE_INTEGRATION=1`), and `image` (builds `Dockerfile.app`,
asserts uid 10001, and asserts the production config guard rejects a CORS
wildcard **inside the built image**).

### Pre-output engineering review (Constitution §23) — done while the run is blocked

The review found six defects in Phase-1 code that has never run against real
infrastructure. All fixed, each with a regression test; the login-counter one
was proven red/green.

| # | Defect | Fix | Commit |
|---|---|---|---|
| 1 | Login lockout incremented `failed_login_count` twice — 3 failed attempts left the count at 4 | Split `record_login_failure` (counter) from `set_lockout` (lock) | `5f29957` |
| 2 | An authorization denial became a 500 when the audit write failed, hiding the refusal | Guard the audit write; always return 403; new `sm_audit_write_failures_total` counter | `5f29957` |
| 3 | Client IP taken from `request.client.host` — spoofable / wrong behind a proxy | `resolve_client_ip` honours `X-Forwarded-For` only for `SM_TRUSTED_PROXY_HOPS` (default 0) | `6e5becc` |
| 4 | 413 body carried a zeroed `request_id` | Read the id from the ambient request context | `6e5becc` |
| 5 | `BodySizeLimitMiddleware` could emit a second `http.response.start` (ASGI violation) | Track `response_started`; re-raise instead of double-sending | `6e5becc` |
| 6 | Audit advisory lock keyed on `hashtext` (int4) — 2^-32 tenant collision | `hashtextextended(key, 0)` (int8) — 2^-64 | `6e5becc` |

**Not verified (Phase 1, Unit 6) — superseded 2026-09-09 by the integration run
below.** At the time this was written the workflow had never run and every
integration test was skipped.

## Verification performed (Phase 1, Unit 6 — integration, executed 2026-09-09)

Docker Desktop was installed on the development machine (engine 29.7.2, WSL2
2.5.10). This is the first non-offline verification in the project.

| Check | Command | Result |
|---|---|---|
| Integration suite | `pytest tests/integration -q -m integration` with `SM_REQUIRE_INTEGRATION=1`, against `docker compose up -d postgres redis` | **52 passed** |
| Concurrency (chain fork) | `test_concurrent_appends_do_not_fork_the_chain`, 5 repeated runs | **green every run** |
| Migrations on real Postgres | `migrate` container in `docker compose up -d --build` | `0001 -> 0002` applied, exit 0; `alembic_version = 0002`; 14 permissions, 5 system roles seeded |
| App on the stack | `curl` against the running `app` container | `/healthz` 200, `/readyz` `{"ready":true}` with live postgres+redis probes, `/api/v1/meta` 200 |
| Image build | `docker build -f deploy/docker/Dockerfile.app -t sentinelmesh/app:local .` | builds |
| Image runs non-root | `docker run --entrypoint id sentinelmesh/app:local -u` | `10001` |
| Prod config guard in the image | `docker run -e SM_ENV=production -e SM_CORS_ALLOWED_ORIGINS='*' ... AppSettings()` | rejected: "SM_CORS_ALLOWED_ORIGINS must not contain '*' in production" |
| Compose config | `docker compose --env-file .env -f deploy/docker/docker-compose.yml config` | valid |
| Non-integration suite | `pytest packages services tests -q -m "not integration"` | **189 passed** |
| Type check | `mypy --strict --python-version 3.11` over all three packages | **no issues in 69 source files** |
| Lint | `ruff check packages services tests migrations scripts` | **All checks passed** |
| Contract schema | `python scripts/gen_contracts.py --check` | up to date |

### First-run defects found and fixed

| # | Defect | Fix |
|---|---|---|
| 1 | **Audit hash chain forked under concurrency.** `_last_hash` ordered a tenant's chain by `created_at, id`. `created_at` is captured by the application *before* the serializing advisory lock, and `uuid7` ids are not monotonic within a millisecond, so two concurrent appends for one tenant could read the same predecessor and both chain onto it. `test_concurrent_appends_do_not_fork_the_chain` caught it (9 distinct `prev_hash` for 10 rows). | Added `audit_log.seq` — `BIGINT GENERATED ALWAYS AS IDENTITY`, assigned by the database *inside* the advisory lock — as the canonical chain order (model + migration `0001`, new `uq_audit_log_seq`, new `ix_audit_log_tenant_id_seq`). `_last_hash` now orders by `seq DESC`; `created_at` capture moved inside the lock. |
| 2 | **Migration `0002` downgrade was broken under asyncpg.** `sa.text("DELETE ... WHERE role_id = ANY(:ids::uuid[])")` — SQLAlchemy reads `::` as an escaped colon, so asyncpg received `ANY($1:uuid[])` → `syntax error at or near ":"`. `upgrade -> downgrade -> upgrade` failed. | Rewrote the downgrade with table constructs and typed `.in_()` bindings; hoisted the `permission` / `role` / `role_permission` `sa.table(...)` definitions to module scope so `upgrade` and `downgrade` share them. |
| 3 | **Integration fixtures bound to a dead event loop.** `database` and `cache` were `scope="session"` async fixtures; pytest-asyncio 1.4 gives each test its own loop, so the reused asyncpg/redis clients raised "attached to a different loop" (24 errors). | Made both fixtures function-scoped, matching every other async fixture in the repo. |
| 4 | **`test_head_is_the_expected_revision` asserted against an un-upgraded database.** It ran `alembic current`, which is empty on a fresh database. | Switched to `alembic heads` (reads the migration scripts), and it now also asserts `current` after an `upgrade`. |

### Corrections to earlier counts

The integration suite is **52 tests**, not 49 — the earlier count predates
`tests/integration/test_rate_limit_redis.py` (3 tests). Occurrences of "49
integration tests" elsewhere in this file are historical.

### Still not verified

- The CI workflow: no job has run. It needs a GitHub remote and `gh auth login`,
  then `bash scripts/push_and_watch.sh`. The local branch is now `main` so the
  `on.push` trigger will match.
- A real OIDC round-trip against Keycloak (the `oidc` compose profile was not
  started).
- Any metric scraped from a running Prometheus; any span at a collector.

## Completed files (Phase 2, Units 1–4)

**Created:**

- `packages/contracts-py/src/sm_contracts/telemetry.py` + `tests/test_telemetry.py`
  (Unit 1).
- `packages/common-py/src/sm_common/security/sensor_auth.py`,
  `packages/common-py/tests/test_sensor_auth.py`,
  `tests/integration/test_sensor_auth_pg.py` (Unit 2 step 1).
- `services/ingestion-gateway/` — `pyproject.toml`, `README.md`, and
  `src/sm_ingestion_gateway/`: `__init__.py`, `__main__.py`, `version.py`,
  `app.py`, `deps.py`, `source_types.py`, `envelope.py`, `sinks.py`, `dedup.py`,
  `metrics.py`, `schemas.py`, `pipeline.py`, `routes/{__init__,ingest,health,metrics}.py`;
  `tests/{conftest,test_ingest,test_envelope,test_dedup,test_health}.py`
  (Unit 2 step 2).
- `packages/common-py/src/sm_common/bus/{__init__,producer.py}` (Unit 3 —
  `EventBusProducer`).
- `services/ingestion-gateway/src/sm_ingestion_gateway/kafka_sinks.py`,
  `services/ingestion-gateway/tests/test_kafka_sinks.py`,
  `tests/integration/test_ingestion_bus_pg.py` (Unit 3).
- `packages/common-py/src/sm_common/bus/consumer.py` (`EventBusConsumer`,
  `dlq_payload`) (Unit 4).
- `services/normalization-engine/` — `pyproject.toml`, `README.md`, and
  `src/sm_normalization_engine/`: `__init__.py`, `__main__.py`, `version.py`,
  `app.py`, `deps.py`, `topics.py`, `engine.py`, `metrics.py`,
  `normalize/{__init__,mappers}.py`, `enrich/{__init__,base}.py`,
  `routes/{__init__,health,metrics}.py`;
  `tests/{conftest,test_normalize,test_engine,test_health}.py`;
  `tests/integration/test_normalization_bus.py` (Unit 4).

**Modified:**

- `packages/contracts-py/src/sm_contracts/{__init__,events,jsonschema}.py`,
  `docs/CONTRACTS.md` (Unit 1 — register telemetry payloads, 34 schema files).
- `packages/common-py/src/sm_common/security/__init__.py` (export `SensorAuth`).
- `packages/common-py/src/sm_common/config.py` +`.env.example`
  (`ingest_dedup_ttl_seconds`, `ingest_batch_max_events`).
- `packages/common-py/src/sm_common/fastapi/ratelimit.py` — `fail_open` flag
  (default `True`; ingestion passes `False`), `_send_429` generalized to
  `_send_error`.
- `deploy/docker/Dockerfile.app` (install `ingestion-gateway`, one image for all
  services), `deploy/docker/docker-compose.yml` (`ingestion-gateway` service;
  `redpanda` dual listener + healthcheck), `Makefile`, `pyproject.toml` (isort
  known-first-party; aiokafka mypy override), `.github/workflows/ci.yml`
  (install + `mypy` cover the new service; `integration` job starts redpanda).
- `packages/common-py/pyproject.toml` (aiokafka dep),
  `packages/common-py/src/sm_common/config.py` + `.env.example`
  (`ingest_*`, `kafka_sasl_*`, `kafka_send_timeout_ms`, `event_bus_enabled`;
  `SM_KAFKA_BOOTSTRAP_SERVERS` default → `localhost:19092`).
- `services/ingestion-gateway/src/sm_ingestion_gateway/{app,deps,pipeline,
  metrics,envelope}.py`, `routes/health.py`, `README.md` (Unit 3 — bus wiring,
  sink-failure policy, sha256 `partition_key`).
- `docs/ARCHITECTURE_DECISIONS.md` (ADR-004 client = aiokafka; ADR-008 dual
  listener).
- Unit 4: `packages/contracts-py/src/sm_contracts/{__init__,events}.py`
  (`make_partition_key`), `sm_common/bus/__init__.py`,
  `services/ingestion-gateway/src/sm_ingestion_gateway/envelope.py` (use the
  shared key), `Dockerfile.app` / `docker-compose.yml` (`normalization-engine`),
  `Makefile`, `.github/workflows/ci.yml`, `pyproject.toml`,
  `docs/{CONTRACTS,REQUIREMENTS_TRACEABILITY,architecture/event-model}.md`.

## Verification performed (Phase 2, Units 2–4 — executed 2026-09-09)

| Check | Command | Result |
|---|---|---|
| Non-integration suite | `pytest packages services tests -q -m "not integration"` | **268 passed** (incl. the 3 §23 regression tests) |
| Integration suite | `pytest tests/integration -q` with `SM_REQUIRE_INTEGRATION=1`, real Postgres 16 + Redis 7 + Redpanda v24.2.11 | **63 passed** |
| Ingest → bus | `test_ingestion_bus_pg.py` — POST → `telemetry.raw`; malformed → `telemetry.raw.dlq` | **2 passed** against real Redpanda |
| Bus → canonical | `test_normalization_bus.py` — `telemetry.raw` → `events.canonical` with lineage; poison → `telemetry.raw.dlq` (wrapped), next good still processes | **2 passed** against real Redpanda |
| Type check | `mypy --strict --python-version 3.11` over all five src trees | **no issues in 106 files** |
| Lint | `ruff check packages services tests migrations scripts` | **All checks passed** |
| Contract schema | `python scripts/gen_contracts.py --check` | up to date |
| Compose config | `docker compose --profile bus config` | valid |
| **Compose stack** | `docker compose --profile bus up -d --build` | all 6 containers **healthy** (postgres, redis, redpanda, app, ingestion-gateway, normalization-engine); `migrate` applied `0001 -> 0002` and exited 0 |
| Service readiness (in-container) | `curl :8000/:8001/:8002 /healthz + /readyz` | all `200` / `{"ready":true}`; ingestion-gateway probes `kafka` healthy (`event_bus=True`), normalization-engine probes `kafka_producer` + `kafka_consumer` healthy (`consumer_group=normalization`) |
| **Live end-to-end** | seed a `sensor` row → `POST :8001/api/v1/ingest/network_flow` → consume `events.canonical` | `202` accepted; the canonical event arrived within ~1s: `event.canonical`, `producer=normalization-engine@0.1.0`, `tenant_id` from the sensor (not the body), `payload.kind=network_flow`, `payload.raw_event_id` = the ingest `event_id`, actor/target = src/dst ip |
| Image job (by hand) | the four `image`-job assertions against `sentinelmesh/app:dev` | uid `10001`; all four service packages + `sm_common.bus` + `aiokafka` import; prod CORS wildcard → exit 1; `ingestion-gateway` prod + `SM_EVENT_BUS_ENABLED=false` → `RuntimeError`, exit 1 |

**Not verified:** the CI jobs on a clean runner (no GitHub remote — the
`image`/`integration` steps were run by hand); a real OIDC round-trip; a scraped
Prometheus / collected span.

### Pre-output engineering review (Constitution §23) — Phase 2

Adversarial read of Units 1–4 (code that has only ever run locally). Three
defects, all fixed with a regression test:

| # | Defect | Fix | Commit |
|---|---|---|---|
| 1 | **`normalization-engine` broke `event_id` idempotency.** It stamped a fresh UUIDv7 on the canonical event every time it processed a raw record. Consumption is at-least-once — a rebalance or crash before the offset commits redelivers the batch — so a redelivered raw record produced a *second* canonical event with a *different* `event_id`, which downstream `event_id` dedup (event-model.md §4) cannot suppress → double detection / double graph write. | `canonical_event_id(raw_event_id) = uuid5(fixed-ns, "canonical:"+raw)` — deterministic, so a redelivery produces the identical `event_id`. `test_redelivery_produces_the_same_canonical_event_id`. | �23 |
| 2 | **`ingestion-gateway` dropped a corrected retry.** The dedup key was set (`SET NX`) *before* payload validation. A sensor that sent a malformed body with an `X-Sensor-Event-Id`, got `422`, fixed the body and retried with the same id → the retry was suppressed as a duplicate (`200`) and the corrected event was never sinked. | `Dedup.forget()` deletes the key on every 4xx path; only an *accepted* event keeps its mark. `test_corrected_retry_after_a_422_is_not_suppressed_as_duplicate`. | �23 |
| 3 | **An empty-string DNS answer DLQ'd the whole event.** `DnsQueryPayload.answers` bounded length but not emptiness; `EntityRef(value="")` then failed `min_length` in the mapper, so `normalize_failed` → DLQ instead of a processed event. | `_bounded_answers` rejects an empty answer at the contract boundary (a clear `422` at ingest, not a silent DLQ downstream). Extra assertion in `test_dns_normalizes_type_and_rcode_and_bounds_answers`. | �23 |

Six-role sign-off (Phase-2 surface): **Principal Engineer** — `ingestion-gateway`
and `normalization-engine` own no other service's data; the bus is the only
coupling; `sm_common.bus` is the shared transport, sink/handler semantics are
per-service; dependency graph acyclic. **Security Engineer** — tenant / sensor
identity is server-side only (payloads are `extra="forbid"`, cannot carry
`tenant_id`); one generic `401` for every sensor-auth failure with `dummy_verify`
for unknown ids; ingestion rate limiter fails **closed**; no secret in any error
body or DLQ record. Open: per-sensor rate quota is still per-IP (recorded);
`identity_link` / enrichment providers not built (R2, later). **SRE** — every
produce failure is a `503` + a metric, never a silent drop; the consumer commits
only after the side effect; poison messages never wedge a partition; `/readyz`
degrades on a broker outage. **Database Engineer** — `SensorAuth` touches
`last_seen_at` throttled to 1/min so a chatty sensor is not a write hot-spot;
no new tables this phase. **ML Engineer** — N/A. **Frontend Engineer** — N/A (no
frontend until Phase 4); the canonical schema is generated.

## APIs

Phase-1 request/response models in `sm_contracts.api`; endpoints implemented in
`services/api-gateway`. Base `/api/v1`. Canonical error contract implemented
(`sm_contracts.errors`).

**Phase 2 (`services/ingestion-gateway`, implemented Unit 2):**
`POST /api/v1/ingest/{source_type}` and `POST /api/v1/ingest/batch`, sensor-
authenticated, bodies validated against `sm_contracts.telemetry`, envelope built
server-side. Response models `IngestAccepted` / `BatchIngestResult` are
service-local (`sm_ingestion_gateway.schemas`), not platform contracts.

## Events

Canonical `EventEnvelope[PayloadT]` **implemented + validated** with envelope
rules (UTC normalization, producer format, clock-skew guard). `EventType`
registry present. `EVENT_PAYLOAD_REGISTRY` maps: `UserEventPayload` (Phase 1);
`NetworkFlowPayload`, `AuthEventPayload`, `DnsQueryPayload`, `ProcessExecPayload`,
`FileAccessPayload`, `CanonicalEventPayload` (Phase 2, Unit 1). The five sensor
payloads are **produced onto `telemetry.raw`** by `ingestion-gateway` — Unit 3
wired the real aiokafka producer (idempotent, `acks=all`), verified end-to-end
against Redpanda; malformed bodies go to `telemetry.raw.dlq`.
`normalization-engine` (Unit 4) **consumes `telemetry.raw` and produces
`events.canonical`** — `CanonicalEventPayload` envelopes with `raw_event_id`
lineage — verified end-to-end against Redpanda (`test_normalization_bus.py`).
Poison records → `telemetry.raw.dlq` (wrapped per event-model.md §5). Consumer
commits offsets only after the side effect. The canonical `event_id` is
**deterministic** — `uuid5` of the raw `event_id` — so an at-least-once
redelivery re-emits the identical `event_id` and downstream dedup suppresses it.
`make_partition_key` (shared) is the single `partition_key` derivation. Topic
catalog + semantics in `event-model.md`. At-least-once; exactly-once not claimed.

## Schemas / migrations

- `sm_contracts` JSON Schema: 22 files in `packages/contracts-ts/schemas/`
  (regenerate: `python scripts/gen_contracts.py`; CI: `--check`).
- Postgres: 8 Phase-1 tables **implemented** as SQLAlchemy models
  (`sm_common.db.models`) and as Alembic migrations:
  - `0001_initial` — `tenant`, `permission`, `role`, `user`, `user_role`,
    `role_permission`, `sensor`, `audit_log`; full PK/FK/unique/check/index;
    `sm_set_updated_at()` trigger on `tenant`/`user`/`role`/`sensor`;
    `sm_audit_log_immutable()` BEFORE UPDATE OR DELETE trigger on `audit_log`;
    `audit_log.seq` (`BIGINT GENERATED ALWAYS AS IDENTITY`, `uq_audit_log_seq`) —
    the canonical hash-chain order; `(tenant_id, seq DESC)` plus descending
    `(tenant_id, created_at)` / `(actor_id, created_at)` audit indexes.
    Reversible.
  - `0002_seed_rbac` — 14 permissions, 5 system roles, role→permission grants,
    ids derived via `uuid5` from a fixed namespace (idempotent, exactly
    reversible); downgrade uses typed `.in_()` bindings (not `ANY(::uuid[])`).
  - Enum columns are `varchar` + `CHECK` rendered from the `sm_contracts`
    enums; a drift-guard test asserts every enum value appears in its CHECK.
  - `identity_link` remains **Phase 2** (owned by `normalization-engine`).
  - **Applied to a real PostgreSQL 16 on 2026-09-09** — `upgrade head`,
    `upgrade -> downgrade -> upgrade`, seed idempotency and the triggers are all
    covered by the passing integration suite.
- Neo4j: constraint/index migration `neo4j/0001` specified, not written.

## Dependencies

- `packages/contracts-py`: `pydantic[email]>=2.9,<3`; dev `pytest>=8`.
- `packages/common-py`: `sm-contracts`, `pydantic>=2.9,<3`,
  `pydantic-settings>=2.5,<3`, `structlog>=24.4`, `argon2-cffi>=23.1`,
  `pyjwt>=2.9,<3`, `fastapi>=0.115,<1`; dev `pytest`, `pytest-asyncio>=0.24`,
  `httpx>=0.27`.
  `pyjwt>=2.9,<3`, `fastapi>=0.115,<1`, `httpx>=0.27`, `anyio>=4`,
  `sqlalchemy[asyncio]>=2.0,<3`, `asyncpg>=0.29`, `redis>=5,<6`,
  `prometheus-client>=0.20`, `opentelemetry-sdk>=1.27`,
  `opentelemetry-exporter-otlp-proto-http>=1.27`; dev `pytest`,
  `pytest-asyncio>=0.24`, `respx>=0.21`.
- Verified installed in `.venv` (Python 3.11.5): pydantic **2.13.5**,
  SQLAlchemy **2.0.52**, plus pydantic-settings, structlog, argon2-cffi, pyjwt,
  fastapi, httpx, asyncpg, redis, prometheus-client, opentelemetry-sdk, respx.
- OIDC is done with `httpx` + `pyjwt` (`PyJWKClient` wrapped via `anyio.to_thread`);
  no `authlib`.
- `alembic>=1.13` installed (**1.19.2** verified) for `migrations/postgres`.

## Environment variables

All in `.env.example` (57 keys, tagged `[required]`/`[optional]`/`[secret]`).
Typed loader + startup validation is Phase 1 (`packages/common-py`).

## Verification performed (Phase 0)

| Check | Command | Result |
|---|---|---|
| Local toolchain | `Get-Command` git/python/node/npm/docker/uv/pnpm/helm/kubectl/java | git 2.55.0, Python 3.11.5, Node 24.14.0, npm 11.9.0, Java 8 present; **docker, uv, pnpm, helm, kubectl, JDK≥11 absent** (ADR-001) |
| Repo skeleton | `mkdir` / `find` | 50 directories under `C:\Users\gmalh\sentinelmesh` |
| Requirements coverage | `grep -c '^### R' docs/REQUIREMENTS_TRACEABILITY.md` | **38** |
| Source hierarchy explicit | manual | PRIMARY (38-point) > SECONDARY (Blueprint) stated in README, ADR intro, traceability intro, CLAUDE.md |
| Fabricated-claim scan | `grep -rniE '(ROC-AUC\|F1 score\|... \|deployed successfully\|benchmark achieved)' docs/ README.md CLAUDE.md` | only negations/prohibitions matched — **no fabricated value** |
| `contracts-py` install | `pip install -e "packages/contracts-py[dev]"` (in `.venv`) | OK; pydantic 2.13.5 |
| Contract unit tests | `python -m pytest packages/contracts-py -q` | **19 passed** |
| Type check | `python -m mypy --strict --python-version 3.11 packages/contracts-py/src/sm_contracts` | **Success: no issues found in 18 source files** |
| Lint | `python -m ruff check packages/contracts-py scripts/gen_contracts.py` | **All checks passed** |
| Schema codegen | `python scripts/gen_contracts.py` then `--check` | 22 JSON Schema files written; `--check` → "up to date" |
| git | `git init` + commits | `0b91ed2` (Phase 0 docs) + Phase-0-close commit |

**Not verified (Phase 0):** anything requiring Docker, Kubernetes, Flink,
Neo4j, Kafka, a GPU, LLM providers, TI providers, or a cloud account. TypeScript
generation was **not run** (`json-schema-to-typescript` not installed — needs
`npm install` under `packages/contracts-ts`); JSON Schema generation is
verified. No runtime service code exists.

## Verification performed (Phase 1, Unit 1 — `common-py`)

| Check | Command | Result |
|---|---|---|
| Install | `pip install -e "packages/common-py[dev]"` (in `.venv`) | OK |
| Unit tests | `python -m pytest packages -q` | **64 passed** (19 contracts + 45 common) |
| Type check | `python -m mypy --strict --python-version 3.11 packages/common-py/src/sm_common` | **Success: no issues found in 17 source files** |
| Lint | `python -m ruff check packages/common-py` | **All checks passed** |

Covered by tests: config defaults + `service_name` required + pool bounds +
**production guards** (CORS `*`, missing secrets, `response_mode=auto` outside
production, `auto` needs policy) + `frozen`; `uuid7` version/variant/ordering;
redaction (sensitive keys, bearer/DSN/JWT patterns, recursion); Argon2id
hash/verify/dummy/empty/malformed/salt; internal JWT roundtrip + wrong
audience/key + rotation + expiry; `SmError` → canonical response + message
redaction; FastAPI request-id echo/preserve, security headers, canonical SmError
body, masked 500, validation-error shape, 413 body-size limit; liveness +
readiness (ok / required-fail / optional-fail / timeout / empty).

**Not verified (Phase 1, Unit 1):** nothing requiring Docker (no Postgres/Redis
client yet — Unit 2); no live OIDC; no OTel exporter. `structlog`/`starlette`
`httpx`-testclient deprecation warnings present, non-blocking.

## Verification performed (Phase 1, Unit 2 — infra clients)

| Check | Command | Result |
|---|---|---|
| Install | `pip install -e "packages/common-py[dev]" respx` | OK; SQLAlchemy 2.0.52 |
| Unit tests | `python -m pytest packages -q` | **81 passed** (19 contracts + 62 common) |
| Type check | `python -m mypy --strict --python-version 3.11 packages/common-py/src/sm_common` | **Success: no issues found in 27 source files** |
| Lint | `python -m ruff check packages/common-py` | **All checks passed** |

Covered by tests (no live infrastructure): engine URL + bounded pool size;
`Database.dispose()` clean with no connection opened; `Cache.key()` prefixing;
`build_redis` constructs without connecting; Prometheus metrics increment +
`render_latest` output + registry isolation; tracing **no-op** when
`SM_OTEL_EXPORTER_OTLP_ENDPOINT` unset (span still works); audit hash chain —
canonical-JSON determinism, hash stability, `verify_chain` detects body tamper
and reorder; OIDC — PKCE `S256` challenge, `authorization_url` params, discovery
issuer-mismatch → `DependencyUnavailable`, code-exchange failure →
`Unauthenticated`, ID-token `aud`/`nonce` checks (signing key stubbed).

**Not verified (Phase 1, Unit 2):** live Postgres / Redis connections, real OIDC
provider, real OTLP collector, JWKS fetch (`PyJWKClient` path) — all need Docker
or network and are Unit 6 / integration. Docker still absent.

## Verification performed (Phase 1, Unit 3 — models + migrations + audit writer)

| Check | Command | Result |
|---|---|---|
| Unit + contract tests | `python -m pytest packages tests -q` | **102 passed** |
| Type check | `python -m mypy --strict --python-version 3.11 packages/common-py/src/sm_common` | **Success: no issues found in 30 source files** |
| Lint | `python -m ruff check packages tests migrations` | **All checks passed** |
| Migration DDL compiles | `alembic -c migrations/postgres/alembic.ini upgrade head --sql` | full DDL + seed INSERTs emitted (offline, no connection) |

Covered by tests: exact Phase-1 table set; `tenant_id` nullability per table;
naming convention applied; `user` uniqueness + lowercase-email + non-negative
login-counter checks; `role` two partial unique indexes; `audit_log` shape
(`metadata` column name, unique `hash`, hex-64 format checks, no
`server_default` on `created_at`); **enum drift guard** (every `sm_contracts`
enum value present in its CHECK); `AuditWriter` genesis hash, advisory lock
taken before the last-hash read, chaining, `verify_chain` round-trip, tamper
detection, platform (`tenant_id IS NULL`) entries; offline migration output
contains all 8 tables, both triggers, partial + DESC indexes, and the seed rows.

**Not verified (Phase 1, Unit 3):** the migrations have **never been applied to a
real database**; `AuditWriter` has **never run against Postgres** — the advisory
lock, the last-hash ordering under concurrency, the constraints, and the
append-only trigger are unexercised. `alembic upgrade head` /
`downgrade base` / `upgrade head` against a live database is a Unit 6
integration test. Docker is still absent.

## External infrastructure requirements (accumulated)

| Need | For | Status |
|---|---|---|
| Docker Desktop | local `docker-compose` (Postgres, Redis, Keycloak, Redpanda, Neo4j, MinIO, Prometheus, Grafana, MLflow) | **INSTALLED 2026-09-09** (engine 29.7.2, WSL2 2.5.10); postgres/redis/migrate/app stack and the 52 integration tests run locally |
| `npm install` under `packages/contracts-ts` | TypeScript contract types for the frontend | not run — JSON Schema is committed; TS is generated on demand |
| JDK 11+ | Apache Flink jobs | **NOT INSTALLED** — Phase 3+ |
| GPU + CUDA | GNN / autoencoder / predictive training at dataset scale | not available — Phase 5 |
| LLM provider credentials | AI analyst / agents / NL hunting / storytelling / RCA | not provided — Phase 6 |
| Threat-intel provider credentials (abuse.ch / OTX / …) | live TI enrichment (optional/flagged) | not provided — Phase 3 optional |
| MaxMind GeoLite2 DB | Geo-IP enrichment | not provided — Phase 2 (degrades gracefully) |
| CICIDS2017 dataset | benchmark parity with architecture | not staged (NSL-KDD, UNSW-NB15, CTU-13, EMBER, LANL staged at `C:\Sentinel_Mesh`) |
| Neo4j Enterprise / GDS production license | production multi-tenant scale, clustering, RBAC (U-003/U-008) | decision required before production |
| Kubernetes cluster + Helm + kubectl | production deployment (R38) | not available |

## Known limitations / open questions

- Open architecture questions **U-001 … U-010** in `ARCHITECTURE_DECISIONS.md`.
  **None blocks Phases 1–4.**
- Per-service `README.md` files (R27) are added as each service is implemented.
- CICIDS2017 not staged.
- Generic `EventEnvelope[T]` JSON Schema is exported only at concrete
  parameterizations listed in `sm_contracts.jsonschema.SCHEMA_MODELS`; each new
  payload must be added there when implemented.

## Exact next action

**PHASE 15 — OBSERVABILITY + BENCHMARKING + EVALUATION. IN PROGRESS.**
ADR-020 already specified the stack (OpenTelemetry + Prometheus + Grafana +
Loki); this phase closes the gap between that spec and what actually runs,
then builds a reproducible ML benchmark/evaluation pipeline that never
claims a number until the benchmark is actually executed (Constitution §3).
Planned units:
1. ✅ **CI-VERIFIED (run `34698614073`, all five jobs, commit `7eee2c1`).**
   Real per-request tracing (`TracingMiddleware`, `current_trace_id`,
   `remote_context_from_trace_id`, wired into all 14 services + both
   envelope-origin points + `RecordProcessor`'s Kafka-consumer span);
   `sm_db_pool_*` + `sm_neo4j_query_duration_seconds` (the two metrics ADR-020
   named that were genuinely missing — model-inference/detection-latency/
   graph-growth already existed under `ml-inference`/`detection-engine`/
   `graph-service`'s own metrics classes, not duplicated); `sm_false_
   positive_feedback_total` registered with no producer yet (no analyst
   "mark as false positive" action exists anywhere in this build — a
   SOC-workflow feature, not this phase's to build); `/health/deps` added to
   the 13 services that lacked it; `prometheus.yml` scrape-target parity
   with every service's real compose port. See "Current phase" above for
   full detail and local verification (924 unit tests, 169 real-infra
   integration tests, real compose-stack smoke test against a rebuilt
   image).
2. ✅ **CI-VERIFIED (run `34699923546`, all five jobs, commit `80a0996`).**
   Tabular IDS benchmark harness core (R24), distinct from Phase 8's
   graph-model pipeline. `sm_ml_training.benchmark` — `nsl_kdd.py` (dataset
   adapter; one-hot vocabulary derived from the train split itself, never
   hardcoded, with an explicit `__unknown` bucket), `metrics.py` (stdlib-
   only ROC-AUC/precision/recall/F1/FPR — no numpy/sklearn, so the metric
   math is auditable), `harness.py` (`run_benchmark` fits `sm_ml.models.
   StatisticalModel` on the train split's benign-only rows, scores the full
   labeled test split; `BenchmarkRun` records dataset id + both file
   sha256s, preprocessing version, split sizes, model + params, seed, every
   metric, real environment). New CLI: `python -m sm_ml_training benchmark
   --dataset nsl-kdd --train <path> --test <path>`.
   **Real, executed run** against the actual locally-staged
   `KDDTrain+.txt`/`KDDTest+.txt`: 125,973 train rows (67,343 benign used
   for the fit), 22,544 test rows (12,833 anomalous) -> **ROC-AUC 0.639039,
   precision 0.581191, recall 0.681914, F1 0.627537, false-positive rate
   0.649367** — reported exactly as measured, deliberately unimpressive,
   no tuning to make it look better (Constitution §3).
   **Dataset-availability finding:** of the phase's named examples
   (CICIDS2017/UNSW-NB15/LANL), only NSL-KDD is present locally in a usable
   *labeled* form — CICIDS2017 was never downloaded (only a `.md5` stub),
   UNSW-NB15 is only raw unlabeled partial Argus/BRO captures, LANL has no
   paired `redteam.txt` ground truth staged. Their adapters + any benchmark
   claim are deferred to Unit 3, pending an actual labeled copy.
   New `ml/datasets/nsl-kdd/MANIFEST.md`. MLflow tracking + a Postgres
   `benchmark_experiment` table deferred (Unit 3/4) — this unit follows
   `ml-training`'s existing artifact-on-disk precedent, not a new
   cross-service DB write path. See "Current phase" above for full detail.
3. ✅ **CI-VERIFIED (run `34701469455`, all five jobs, commit `498b98b`).**
   Baseline IDS comparison (R24): `run_benchmark(..., model=
   "isolation_forest")` — scikit-learn's `IsolationForest` trained directly
   in the harness (`sm-ml[serving]`, new `ml-training[benchmark]` extra,
   installed in CI), fit on the same benign-only NSL-KDD train rows, scored
   one row at a time against the same test split. Real, executed run:
   ROC-AUC 0.935499, precision 0.961297, recall 0.621289, F1 0.754769,
   false-positive rate 0.033055, mean detection latency 24.836165 ms/row —
   vs. the statistical baseline's 0.639039 AUC / 0.649367 FPR / 0.054062
   ms/row: substantially more accurate, ~460x slower per row, a real
   measured tradeoff. Re-checked CICIDS2017/UNSW-NB15/LANL local
   availability — unchanged, still not usable in labeled form, no adapter
   built, no number claimed. See "Current phase" above for full detail.
4. ✅ Grafana provisioning (real datasource + a 14-panel dashboard, real
   bug fixed: a nested bind mount fails on Docker Desktop) + benchmark
   result storage (`benchmark_experiment` migration `0014` + plain-asyncpg
   `save_benchmark_run`) + `api-gateway` read path (`SqlBenchmarkRepository`,
   `GET /api/v1/soc/benchmarks[/{id}]`, `ops:read`-gated) + frontend
   `/benchmarks` page + phase close. Second real bug found by running the
   finished dashboard against live data: `Metrics.observe_http` had no
   caller anywhere in the platform since whichever phase declared it —
   fixed with a new `sm_common.fastapi.MetricsMiddleware`, wired into all
   14 services. Full real end-to-end proof (real CLI run → real Postgres
   insert → real authenticated BFF read; real curl against Grafana's API;
   real Prometheus query showing real HTTP-metric samples). See "Current
   phase" above for full detail and the Phase 15 exit report below.

Exit next action after Phase 15: **PHASE 16 — Kubernetes + Enterprise
Deployment** (prompt not yet given — do NOT start speculatively; the next
session resumes here).

**PHASE 14 — REPORTING + ATTACK STORYTELLING. COMPLETE / CI-VERIFIED (all
five jobs, final run `34641513223`; see exit report above).** Every generated
narrative must distinguish ACTUAL SYSTEM EVIDENCE from INFERENCE from
PREDICTION from SYNTHETIC DEMO DATA (Constitution §3) — never invent an
incident. Planned units:
1. ✅ **CI-VERIFIED (run `34597754999`, all five jobs).** Core report data
   layer, no service yet. `sm_contracts.report` (top-level, mirrors
   `chains.py`/`memory.py`'s pattern of an entity beside its own topic
   payload): `GroundingKind` (`evidence` / `inference` / `prediction` /
   `synthetic` — deliberately not named `Provenance`, which `threatintel.py`
   already uses for a different meaning), `GroundedStatement` (`text` +
   `tier` + optional `ref` — the building block for every finding,
   recommendation, and timeline point), `ReportTimelineEntry`, `ReportAsset`,
   `Report` (incident metadata, timeline, affected assets, detection ids,
   evidence, chain ids, technique ids, threat score, findings,
   recommendations, confidence, provenance, `missing_sections` for a
   `partial` report, `storage_key`), `ReportGeneratedPayload` for the
   already-pre-declared `report.generated` topic
   (`EventType.report_generated`, confirmed still present from an earlier
   phase's anticipation). New permission `reports:read` added to
   `PermissionCode` (enum only this unit; the CHECK-widening migration and
   grants land with the BFF unit, matching `memory:read`'s Phase 13
   precedent) — `reports:generate` (a placeholder since an earlier phase) is
   now the write-side counterpart.
   `sm_common.db.report_models` — `ReportTemplateRow` (`report_template`,
   one seeded default per `ReportKind`) and `ReportRow` (`report`, the
   assembled `Report` body stored whole as JSONB — a report is a
   point-in-time snapshot, never queried by its internal fields, so it is
   deliberately not normalized further). Migration `0011` creates both
   tables and seeds the four default templates; seeding a JSONB column from
   Alembic needed an explicit `CAST(:sections AS jsonb)` in raw SQL text
   rather than `op.bulk_insert` with a JSONB-typed table proxy — online,
   asyncpg binds a bulk-insert parameter as text and Postgres refuses the
   *implicit* text→jsonb assignment cast for a bound parameter (only a
   literal gets that); offline (`alembic ... --sql`), a raw Python list has
   no literal renderer at all. An explicit `CAST` in the SQL text is
   unaffected by either problem.
   `sm_common.objectstore` (new; ADR-019) — `ObjectStore` (async, `aioboto3`,
   MinIO-locally/S3-compatible-in-prod) + `safe_key()` (the only way to build
   an object key: rejects `.`/`..`, path separators, and anything outside a
   conservative allow-list — the path-traversal / malicious-filename guard).
   `ensure_bucket()` creates a bucket with default SSE-S3 (AES256) encryption
   if missing; `put_bytes()` / `presigned_get_url()` / `ping()` round out the
   client. Real finding: MinIO (unlike AWS S3) refuses *any* server-side
   encryption request — bucket-default or per-object header — unless a KMS
   backend is configured, even for plain AES256; fixed by giving the compose
   `minio` service a fixed, non-secret `MINIO_KMS_SECRET_KEY` (local/CI only,
   protects nothing sensitive) so local runs exercise the same encrypted
   path production does, rather than skipping the requirement.
   Local: ruff + `mypy --strict` clean (368 files, full CI static tree),
   **833 unit tests** (11 new: `safe_key` validation + `ObjectStore`
   construction) + `gen_contracts --check` (97 JSON Schema files, 5 new);
   real-Postgres migration round-trip (`tests/integration/test_migrations_pg.py`,
   updated for head `0011` + the two new tables) and a new real-MinIO
   integration suite (`tests/integration/test_objectstore_s3.py`, 5 tests:
   put + presigned-get round-trip, `ping` success/failure, idempotent
   `ensure_bucket`, `safe_key` rejection before touching the backend) both
   green; `Dockerfile.app` builds, `sm_common.objectstore` +
   `sm_common.db.report_models` import in the image, non-root uid confirmed.
   CI's `integration` job needed a MinIO container: `SM_REQUIRE_INTEGRATION=1`
   turns "unreachable" into a hard failure, not a skip, and GitHub Actions'
   `services:` containers cannot supply the `server /data` start command
   MinIO's image needs — the exact constraint the workflow already documents
   for Redpanda — so it runs as a plain `docker run` step with a health-check
   wait loop, same fixed `MINIO_KMS_SECRET_KEY` as the compose service.
   First push (commit `ea56100`) went red on this gap; verified the fix by
   replicating the exact CI container + credentials locally before the
   follow-up push. **CI-VERIFIED (run `34597754999`, all five jobs).**
2. ✅ `services/reporting-service` (port 8013, module `sm_reporting_service`,
   HTTP-triggered — no Kafka consumer). Content gathering hits every
   dependency `docs/architecture/service-catalog.md` names for this
   service: `detection-engine` (`content_repository.py`, direct Postgres
   read — it exposes no read API of its own, mirroring `api-gateway`'s own
   `SqlSocRepository`), `graph-service` / `mitre-service` / `ai-analyst` /
   `memory-service` (`content_client.py`, internal HTTP, mirrors
   `api-gateway`'s `InternalServiceClient`). `ai-analyst`'s grounded
   `/explain` narrative is only called when the report's subject *is* a
   detection (`ExplainRequest`'s subject type has no host/ip/domain/
   identity variant); `memory-service`'s lateral-movement prediction is
   folded into `findings` tier `prediction`, dropped entirely when
   `confidence == 0.0` (mirrors `sm_ml.predict`'s own convention — never
   present a non-prediction as a result). Every dependency's failure lands
   its section in `missing_sections` -> report `partial`, filtered against
   the report kind's own `report_template.sections` first (a section the
   template never asked for is not a gap). PDF rendering
   (`renderer.py`, `reportlab`, added to `services/reporting-service`'s own
   `pyproject.toml` — not `sm_common`, since PDF rendering is
   reporting-service-specific). `POST /api/v1/reports` + `GET
   /api/v1/reports/{id}` (pre-signed download via `sm_common.objectstore`,
   5-minute TTL). Object-storage failure (never a content-dependency
   failure) is the only thing that makes a report `failed`, per
   service-catalog. Produces `report.generated`.
   Local: ruff + `mypy --strict` clean (384 files, full CI static tree),
   **860 unit tests** (27 new: 9 generator, 6 content-client (`respx`), 5
   renderer (`pypdf`-verified text extraction), 7 route) + `gen_contracts
   --check`; new real-Postgres integration test
   (`tests/integration/test_reporting_repositories_pg.py`, 6 tests:
   tenant-scoped detection/report reads, the app-level entity filter over
   `detection.entities`, the `report`/`report_template` round trip through
   JSONB); full `tests/integration` suite (real Postgres/Redis/Neo4j/
   MinIO/Kafka) green; `Dockerfile.app` + `docker-compose.yml` wired
   (profile `detect`, port 8013, depends on `postgres` + `migrate`) and
   manually smoke-tested end to end against the real compose stack — a
   `POST /api/v1/reports` for a subject with no telemetry came back
   `partial` (graph-service/memory-service unreachable in the smoke
   environment, correctly listed in `missing_sections`) with a real PDF
   uploaded to MinIO, downloaded via its presigned URL, and confirmed a
   valid single-page PDF. CI's `image` job import-check line extended
   (`sm_reporting_service`, `sm_common.objectstore`, `reportlab`,
   `aioboto3`). **CI-VERIFIED (run `34631135008`, all five jobs, first
   push — no follow-up fix needed).**
3. ✅ Attack storytelling in `services/ai-analyst` (R33). "Incident" in
   `GET /api/v1/incidents/{chain_id}/narrative` is an attack chain — this
   platform has no separate `Incident` entity (§3 still lists one
   PLANNED) — so the path id is `correlation-engine`'s own chain id.
   `chains_client.py` (copied from `sm_memory_service`'s, audience
   `correlation-engine`) fetches the chain; `narrative.py`'s
   `NarrativeComposer` builds one `NarrativeBeat` per `ChainStageModel`
   **deterministically** — stage, detection_ids, technique_ids, straight
   from the chain, never touched by the LLM — then composes ONE grounded
   summary paragraph reusing `IncidentAnalyst.explain`'s exact
   citation-and-retry mechanism (every sentence must cite a beat's
   `stage` value, one repair turn, then a deterministic factual template
   with `degraded=True` — never a third try to invent a stage). A chain
   whose `subject_id` is simulation-generated
   (`sm_ml.scenario.is_synthetic_id`) narrates with every beat tagged
   `GroundingKind.synthetic` and `Narrative.simulated=True` — the
   contract-level version of Phase 12's "SIMULATION" badge, not a
   separate ad hoc flag. New Postgres `narrative` table (migration
   `0012`, ai-analyst's first — this service had no database before),
   upserted per `(tenant_id, chain_id)` on every `GET` (a narrative is a
   snapshot, not append-only). ai-analyst gained `sm-ml` (base install
   only — `is_synthetic_id`) and `httpx` as direct dependencies.
   Local: ruff + `mypy --strict` clean (390 files, full CI static tree),
   **873 unit tests** (13 new: 9 composer incl. grounding-tier and
   no-fabrication assertions, 4 route) + `gen_contracts --check` (99 JSON
   Schema files, 2 new: `Narrative`, `NarrativeBeat`); new real-Postgres
   integration test (`tests/integration/test_narrative_repository_pg.py`,
   4 tests: tenant-scoped get, upsert-replaces-not-duplicates, simulated
   round trip); full `tests/integration` suite green. Manually verified
   end to end against the real compose stack: inserted a real
   `attack_chain`/`attack_chain_stage` row, called the narrative endpoint
   through the real `correlation-engine` over the network, got back a
   beat matching the stage exactly and a `degraded=True` factual summary
   (no LLM key configured in the smoke environment) — then repeated with
   a `sim-`-prefixed subject id and confirmed every beat came back tagged
   `synthetic` with `simulated: true`. Wiring: `docker-compose.yml`'s
   `ai-analyst` block gained `SM_CORRELATION_ENGINE_URL` (compose service
   name — previously unset, a real gap the smoke test caught: without it
   the container defaults to `localhost:8009`, unreachable from inside
   its own container) and a `depends_on: postgres, migrate` it didn't
   need before. **CI-VERIFIED (run `34635710315`, all five jobs, first
   push — no follow-up fix needed).**
4. ✅ `api-gateway` BFF: `routes/reports.py` — `POST /api/v1/soc/reports`
   (`CreateReportRequest` has no `requested_by` field at all, `extra=
   "forbid"` rejects a client-supplied one — the server always derives it
   from the session principal; a `compliance`-kind report additionally
   requires `lead`/`tenant_admin`, checked in route code on top of the
   `reports:generate` permission), `GET /api/v1/soc/reports/{id}`
   (`ReportDownload` — promoted from a reporting-service-local definition
   into `sm_contracts.report`), `GET /api/v1/soc/incidents/{chain_id}/
   narrative` (gated on the existing `detections:read` tier rather than a
   new permission code). Migration `0013` widens `permission.code`'s
   CHECK and seeds/grants `reports:read` to all five roles (same tier as
   `memory:read`). `frontend/web/app/(soc)/reports` (builder + a
   session-local library — no server-side list endpoint exists yet +
   lookup-by-id with the presigned download link) and `.../story`
   (chain-id lookup -> deterministic beats + one grounded summary, with a
   "Simulation" badge when `Narrative.simulated`), both via a new shared
   `GroundingTag` component (`.tier-badge` CSS, `synthetic` reusing the
   Phase 12 "Simulation" amber).
   Local: **883 unit tests** (10 new: BFF proxy, `requested_by`-never-
   trusted 422, compliance-role-gate 403/200, get-report 404/200, narrative
   permission/404/200) + `gen_contracts --check` (100 JSON Schema files, 1
   new: `ReportDownload`); full frontend gauntlet (`eslint` clean, 62
   vitest tests across 17 files, `npm run build` — 21 routes,
   `contracts-ts` typecheck clean). Manually smoke-tested end to end
   against the real compose stack: seeded a real tenant/user/analyst-role
   grant via direct SQL, logged in via real `/api/v1/auth/login`, created
   a real report through the BFF (confirmed `requested_by` server-derived,
   not client-supplied), fetched it back with a real presigned MinIO
   download URL, hit the narrative endpoint (real 404 for a nonexistent
   chain), and confirmed the compliance-report role gate produces a real
   403 for an `analyst`-role user.
   Real finding, external not code: Docker Hub's `minio/minio` repository
   started denying anonymous pulls of the pinned release tag
   (`pull access denied ... repository does not exist`) between Unit 3's
   CI run and this one. Confirmed genuine (not transient, not GH-runner-
   IP-specific) by reproducing the identical denial via a local
   `docker pull` and one `gh run rerun --failed`, and confirming
   `quay.io/minio/minio` serves the identical image digest
   (`sha256:9535594ad4122b7a78c6632788a989b96d9199b483d3bd71a5ceae73a922cdfa`).
   First push (commit `18c9e1f`, CI run `34640559225`) went red on this gap
   alone (all four other jobs green); fixed by repointing both
   `docker-compose.yml`'s `minio` service and CI's "Start MinIO" step at
   `quay.io/minio/minio` (commit `a7b0704`).
   `docs/REQUIREMENTS_TRACEABILITY.md` R22 and R33 -> IMPLEMENTED, each
   with an explicit deviation noted (R22: no server-side report list
   endpoint yet, compliance gate is route-code not a second permission;
   R33: "incident" = attack chain id, beats deterministic/LLM only for the
   summary). **CI-VERIFIED (run `34641513223`, all five jobs).**
   **This closes Phase 14** — see the exit report above.

Exit next action after Phase 14: **PHASE 15 — Observability + Benchmarking**
(prompt not yet given — do NOT start speculatively; the next session resumes
here).

**PHASE 13 — THREAT MEMORY + PREDICTIVE INTELLIGENCE. COMPLETE /
CI-VERIFIED (all five jobs, final run `34591054542`).** Three stores, one graph database (ADR-011);
never present a prediction as fact. Planned units:
1. ✅ **CI-VERIFIED (run `34582276848`, all five jobs).** `sm_ml.memory`
   (`technique_feature_vector`, `cosine_similarity` — deterministic, not a
   trained embedding), `sm_common.db.memory_models` (`ThreatMemoryRow` /
   `CampaignRow` / `AdversaryFingerprintRow`, each a `pgvector` `vector(32)`
   column + `hnsw`/`vector_cosine_ops` index), migration `0009`
   (`CREATE EXTENSION vector`), `sm_contracts.memory` (`ThreatMemory` /
   `Campaign` / `AdversaryFingerprint` / `SimilarityMatch` — the feature
   vector itself is never returned). Postgres image swapped to
   `pgvector/pgvector:pg16` in compose + CI.
2. ✅ `services/memory-service` (port 8012) — consumes `attack_chains`
   (group `memory`), fetches the full chain from `correlation-engine`
   (`ChainsClient`, internal JWT — the topic event is a thin projection with
   no technique data), upserts a `ThreatMemory` pattern, matches-or-starts a
   `Campaign` (pgvector cosine similarity against active campaigns,
   `SM_MEMORY_CAMPAIGN_SIMILARITY_THRESHOLD`, exact-fallback on a DB error),
   upserts an `AdversaryFingerprint`, and produces `campaign.updates`
   (`CampaignUpdatePayload`, a thin projection mirroring `AttackChainPayload`).
   `POST /api/v1/memory/similar` + `GET .../patterns`, `.../fingerprints/...`,
   `.../campaigns...` (internal-JWT only). `RetentionSweeper` — the deletion
   lifecycle: `active -> dormant -> closed` on inactivity
   (`SM_MEMORY_DORMANT_AFTER_DAYS` / `SM_MEMORY_CLOSE_AFTER_DAYS`), delete
   patterns / fingerprints / long-closed campaigns past
   `SM_MEMORY_RETENTION_DAYS`, mirroring `threat-intel-service`'s expiry
   sweeper. `sm_contracts.memory` moved out of `api/` (Unit 1's placement)
   to sit beside its own `campaign.updates` topic payload, matching
   `chains.py`'s precedent.
   Local: ruff + `mypy --strict` clean (358 files, full CI static tree),
   **790 unit tests** (16 new: 9 route, 5 ingest, 2 retention) +
   `gen_contracts --check`; real-Postgres integration test
   (`tests/integration/test_memory_repository_pg.py`, 6 tests) caught a real
   bug — `Database`'s sessionmaker runs `autoflush=False` platform-wide, so
   the retention sweep's campaign-status transitions were invisible to the
   same-transaction DELETE that followed until an explicit `flush()` was
   added; full `tests/integration` suite green; `Dockerfile.app` builds,
   `sm_memory_service` + `pgvector.sqlalchemy` import in the image, non-root
   uid confirmed; CI + `deploy/docker/{Dockerfile.app,docker-compose.yml}`
   wired (profile `detect`, depends on `postgres` + `migrate`;
   `SM_CORRELATION_ENGINE_URL` overridden to the compose service name — the
   one new cross-service call this unit introduces). **CI-VERIFIED (run
   `34586331308`, all five jobs).**
3. ✅ `sm_ml.predict` (`MODEL_VERSION = "heuristic-v1"` — no trained model;
   `predict_attack_progression` / `predict_next_action` /
   `predict_lateral_movement` / `predict_threat_trajectory`, every one a
   deterministic rule over data already on hand, `confidence=0.0` with a
   stated reason when the input is underdetermined, never a guess).
   `sm_contracts.api.prediction.Prediction` (`prediction`, `confidence`,
   `evidence`, `features`, `model_version`, `generated_at`; `subject_type`
   is `None` for the campaign-level `threat_trajectory`). `memory-service`
   gains `POST /api/v1/predict/{attack-progression,next-action,
   lateral-movement,threat-trajectory}` (internal-JWT only), wiring the
   heuristics to `ChainsClient` + `MemoryRepository` (new
   `list_fingerprints` for lateral-movement candidates).
   Local: ruff + `mypy --strict` clean (363 files, full CI static tree),
   **812 unit tests** (22 new: 14 heuristics, 8 route) +
   `gen_contracts --check` (92 JSON Schema files); full `tests/integration`
   suite green; `Dockerfile.app` builds, image imports clean, non-root uid
   confirmed. **CI-VERIFIED (run `34588573722`, all five jobs).**
4. ✅ `api-gateway` `routes/memory.py` — full BFF proxy for threat-memory
   retrieval + predictions under `/api/v1/soc/{memory,predict}/...`, new
   permission `memory:read` (migration `0010`, granted to every role
   including `read_only`). `frontend/web/app/(soc)/memory` — campaigns (+
   predict trajectory), fingerprint lookup (+ predict lateral movement),
   similarity search, chain predictions — every prediction rendered with
   its confidence/evidence/model version. Local: ruff + `mypy --strict`
   clean (364 files), **822 unit tests** (10 new BFF) + `gen_contracts
   --check` (92 JSON Schema files); full `tests/integration` suite green;
   `frontend/web`: lint clean, build OK (18 routes), **56 vitest tests** (3
   new + 2 `contract.test.ts` fixtures); `Dockerfile.app` builds, image
   imports clean, non-root uid confirmed. **CI-VERIFIED (run `34591054542`,
   all five jobs) — closes Phase 13.** See the exit report above for the
   full §23 safety review.

Exit next action after Phase 13: **PHASE 14 — Reporting + Storytelling**
(prompt not yet given — do NOT start speculatively; the next session resumes
here).

**PHASE 12 — SIMULATION + DECEPTION + SECURITY DIGITAL TWIN. COMPLETE /
CI-VERIFIED (all five jobs, final run `34576850936`).** Everything synthetic,
isolated, deterministic; scenarios run against a model, never real systems.
Units delivered:
1. ✅ **CI-VERIFIED (run `34449930913`).** `sm_ml.twin` — `TwinModel`
   (`TwinAsset` / `TwinRelation` / `TwinWeakness`, `build_twin` validates +
   freezes + sorts → deterministic, stdlib), `attack_paths` (bounded simple
   paths, feasibility-ordered), `blast_radius` → `BlastRadiusReport` (reached
   set, per-hop, critical-reached, criticality-weighted score, amplifying
   weaknesses), `stress_test` + `DefensiveControl` → which paths a control set
   breaks + residual risk + most-valuable control.
2. ✅ `sm_ml.scenario` — `build_synthetic_env(seed)` (deterministic, every id
   `sim-`-prefixed — `is_synthetic_id` is the check every target passes
   through), `ScenarioSpec` (apt / ransomware / insider / brute_force, Pydantic
   frozen + `extra=forbid`), `validate_spec` (raises `ScenarioIsolationError`
   unless every target is a synthetic id present in the env — a spec naming a
   real-looking id like `host-01` or one from a different env is refused before
   anything runs), `run_scenario` (a seeded-RNG deterministic ordered
   `SimEvent` list per kind — recon/initial-access/lateral/collection/exfil for
   apt, a failure burst + one success for brute_force, discovery + write bursts
   for ransomware, an off-hours login + bulk reads for insider; every event
   `simulated=True` + its `scenario_id`; `intensity` scales volume),
   `replay_run` (deterministic read-only slice; an inverted window raises).
   Local: ruff + `mypy --strict` clean (42 files), **723 unit tests** (17 new)
   + `gen_contracts --check`; `Dockerfile.app` builds + `sm_ml.scenario`
   imports. **CI-VERIFIED (run `34569040279`).**
3. ✅ `services/simulation-service` (port 8011) — `POST
   /api/v1/sim/scenarios/run` (isolation-refused target → 422, `feed_pipeline`
   without the event bus → 422, deterministic run given the same seed) + a
   deception decoy registry (`POST/GET/DELETE /api/v1/deception/decoys...`,
   `decoy` / `decoy_interaction` tables, migration `0007`; isolation
   invariants: `network_boundary` is schema- and DB-CHECK-constrained to
   `isolated` / `dmz-isolated`, never `production`; decoys carry no credential
   field; interaction capture is one-way; teardown is idempotent and a
   torn-down decoy captures nothing further). `sm_contracts.api.simulation`
   added (6 models, wired into `jsonschema.py` — 84 JSON Schema files).
   Local: ruff + `mypy --strict` clean (92 files across contracts-py /
   common-py / simulation-service), **739 unit tests** (23 new) +
   `gen_contracts --check`; real-Postgres integration test
   (`tests/integration/test_simulation_pg.py`, 4 tests: tenant isolation,
   idempotent teardown keeps history, torn-down decoy captures nothing, the
   `network_boundary` CHECK rejects `'production'` at the database level, not
   just the schema); full `tests/integration` suite (all real infra) green;
   `Dockerfile.app` builds, `sm_simulation_service` imports in the image,
   non-root uid 10001 confirmed; CI (`.github/workflows/ci.yml`) and
   `deploy/docker/{Dockerfile.app,docker-compose.yml}` wired (profile
   `detect`, depends on `postgres` + `migrate`). **CI-VERIFIED (run
   `34572530014`, all five jobs).**
4. ✅ `sm_ml.twin.twin_from_synthetic_env` + `GET /api/v1/sim/twin` +
   `POST /api/v1/sim/twin/blast-radius` on `simulation-service`; new
   permissions `simulation:run` / `deception:manage` (migration `0008`,
   widens the `permission.code` CHECK, seeds + grants both — not to
   `read_only`); `api-gateway` `routes/simulation.py` — full BFF proxy for
   scenario-run + twin + blast-radius + the deception registry under
   `/api/v1/soc/{simulation,deception}/...`, every route `require_permission`
   + CSRF on writes; a downstream `422` is now `ValidationFailed` (was a
   misleading `DependencyUnavailable`). `frontend/web/app/(soc)/simulation`
   (run form, twin table, per-asset blast-radius) and `.../deception`
   (register/list/teardown/interactions), both badged "SIMULATION"; nav gated
   on the new permissions. Local: ruff + `mypy --strict` clean (339 files,
   full CI static tree), **763 unit tests** (24 new) + `gen_contracts --check`
   (87 JSON Schema files); `tests/integration` full suite green (real
   Postgres/Redis/Neo4j) incl. updated `test_migrations_pg.py` (head `0008`,
   16 permissions); `frontend/web`: lint clean, build OK (17 routes), **51
   vitest tests** (9 new + 3 `contract.test.ts` fixtures); `Dockerfile.app`
   rebuilds, image imports clean, non-root uid 10001 confirmed. **CI-VERIFIED
   (run `34576850936`, all five jobs) — closes Phase 12.** See the exit
   report above for the full §23 safety review.

**Exact next action: PHASE 13 — Memory + Predictive Intelligence**
(prompt not yet given — do NOT start speculatively; the next session resumes
here).

**PHASE 11 — THREAT HUNTING + NATURAL LANGUAGE QUERYING. Units 1–3 done.** Planned units:
1. ✅ **CI-VERIFIED (run `34446018571`).** `sm_contracts.api.hunt` — `QueryPlan`
   (closed schema: `HuntIntent` ∈
   {find_entity, list_related, path_between, detections_for, chains_for,
   indicator_sightings, technique_usage}, typed `EntitySelector`s, `rel_types`
   allow-list, `QueryLimits`), `NlHuntRequest`, `PlanResponse`, `HuntResult`.
   `graph-service` `hunt.py` — `validate_plan` (selector count + type per intent;
   `rel_types` ⊆ `GRAPH_REL_TYPES`; `rel_types` only on `list_related`),
   `compile_plan` (intent → one constant parameterized Cypher; label/reltype/int-
   depth are the only interpolations, all allow-listed; every value is a `$`
   param), `HuntRunner`. `POST /api/v1/graph/hunt` (internal JWT; bad plan → 422).
   `SM_HUNT_MAX_ROWS` (200) / `SM_HUNT_MAX_DEPTH` (3). Local: ruff + `mypy --strict`
   clean (305 files), **679 unit tests** (17 new: every intent compiles read-only
   + parameterized, a Cypher-injection string stays a `$` param, plan-validation
   rejections, depth/row clamps, fingerprint determinism, route authz + 422) +
   `gen_contracts --check`; real-Neo4j `test_hunt_neo4j.py` (hunt runs,
   tenant-scoped, cross-tenant isolation, hallucinated entity → empty).
2. ✅ NL → `QueryPlan` in `ai-analyst` — `HuntPlanner` (`POST /api/v1/hunt/plan`):
   the LLM emits **only** a `QueryPlan` (parsed into the closed model) or
   `{"unsupported": true}`; non-JSON / invalid intent / no LLM →
   `PlanResponse(supported=false)`, **never a query**. `explain_hunt` +
   `POST /api/v1/hunt/explain` (grounded, cites the plan; deterministic baseline
   without an LLM). `api-gateway` `POST /api/v1/soc/hunt`
   (`require_permission(hunt:query)` + CSRF, tenant from the session `Principal`)
   orchestrates: `body.plan` → run directly; `body.query` → `ai-analyst`
   `/hunt/plan` (unsupported → `SocHuntResponse(supported=false)`, not executed) →
   `graph-service` `/graph/hunt` → `/hunt/explain` (best-effort). The NL text is
   never sent to `graph-service`. `hunt_query` history (`sm_common.db.HuntQueryRow`
   + migration `0006`, append-only; `SqlSocRepository.record_hunt`).
   `SocHuntRequest` / `SocHuntResponse` / `HuntExplainRequest`. Local: ruff +
   `mypy --strict` clean (308 files), **694 unit tests** (28 new) + `gen_contracts
   --check`; real PG `test_migrations_pg.py` (0006 up/down) + real Neo4j
   `test_hunt_neo4j.py`; `Dockerfile.app` builds + imports.
   **CI-VERIFIED (run `34447606633`, all five jobs).**
3. ✅ `frontend/web/app/(soc)/hunt` — an "Ask" NL mode (`{query}`) and a "Quick
   query" structured form (`{plan}`, no LLM), both rendering the **compiled
   `QueryPlan`** JSON for transparency, the grounded explanation, a rows table,
   and a "Pivot" action (runs `list_related` on a result row's entity). Nav entry
   gated on `hunt:query`. `api.hunt(body, csrfToken)` helper + `contract.test.ts`
   `SocHuntResponse` fixture. Local: `npm run lint` clean, `npm run build` OK
   (15 routes), **41 vitest tests** (3 new); ruff + `mypy --strict` unchanged
   (Unit 3 is frontend-only), `gen_contracts --check`. Phase 11 exit report + §23
   + `REQUIREMENTS_TRACEABILITY` R18 / R32 → IMPLEMENTED + `CONTRACTS.md` §7.1
   IMPLEMENTED.

**PHASE 11 is CLOSED — CI-VERIFIED, final run `34448406595` (all five jobs).**

Exit next action after Phase 11: **PHASE 12 — Simulation + Deception + Digital
Twin** (prompt not yet given — do NOT start speculatively; the next session
resumes here).

**Phase 4 is COMPLETE and CI-VERIFIED** (Units 1–4; final run `34350607501`).

**Phase 5 is COMPLETE and CI-VERIFIED** (Units 1–5; commits `5c7da92` / `d6b2c1a`
/ `fe63df5` / `a40c22f` / `cd6e02e`; final run `34358654888` — all four jobs).

**Phase 6 Units 1–5 done.** Units 1–3 CI-green (commits `b468eca` / `9778fb7` /
`1da61e1`); Unit 4 committed `43cbcc5`. Unit 5 (enrichment wiring + close)
locally verified: ruff clean, `mypy --strict` over 12 trees (224 files),
480 unit tests + `gen_contracts --check`, **117** real-infra integration tests
(PostgreSQL 16 + Redis 7 + Redpanda + Neo4j 5), `Dockerfile.app` build green.
New: `ThreatIntelEnricher`, `rule.ti.known_bad_indicator`,
`test_ti_enricher.py` (6), `test_ti_enrichment_chain_pg.py` (2),
`SM_TI_ENRICHMENT_ENABLED`. Phase 6 exit report + §23 review + traceability
R7 / R9 → IMPLEMENTED + `CONTRACTS.md` "Phase 6 closed" written.

**Phase 6 is CLOSED — CI-VERIFIED, run `34366970151` (all four jobs).**

**Phase 7 — Attack Chain Reconstruction + Threat Scoring. Units 1–3 DONE.**
Unit 1 CI-green (run `34370745672`; commit `daaf20e`); Unit 2 CI-green (run
`34373057354`; commit `8c3a177`). Unit 3 (graph projection + mitre `attack_chains`
consumer + `threat_score` handoff + close): local gauntlet green — ruff,
`mypy --strict` over 13 src trees (243 files), 523 unit tests +
`gen_contracts --check`, real-PG + real-Neo4j chain integration (`test_chain_*`,
`test_chain_pipeline_e2e_pg.py`), `Dockerfile.app` build. Phase 7 exit report +
§23 + `REQUIREMENTS_TRACEABILITY` R6/R8 + `CONTRACTS.md` written. **Commit Unit 3,
push, confirm CI green → closes Phase 7.**

**Phase 7 is CLOSED — CI-VERIFIED, run `34406870398` (all four jobs).**

**PHASE 9 — ENTERPRISE SOC DASHBOARD. CLOSED — CI-VERIFIED, all five jobs, final
run `34428106928`** (unit runs `34424869328` / `34426774409`). Units 1–4
(`15f5d1c` / `790fdf5` / `dac8e50` / `3d8c401`). SOC BFF + generated typed client
+ every SOC view + a Cytoscape attack-graph explorer with an accessible list
fallback + honest-poll realtime. `sm_contracts.api.graph` promoted. Phase 9 exit
report + §23 + `REQUIREMENTS_TRACEABILITY` R13 / R25 → IMPLEMENTED (P9 core;
WebSocket / `notification-service` / cinematic replay / Playwright deferred) +
`CONTRACTS.md` "Phase 9 closed".

**PHASE 10 — AI SECURITY ANALYST + MULTI-AGENT DEFENSE. Units 1–3 DONE (Unit 3
local gauntlet green, awaiting CI).**
1. ✅ **CI-VERIFIED (run `34429226626`).** `packages/ai-py` (`sm_ai`) — the
   untrusted-LLM boundary: provider-neutral messages, `LlmProvider`,
   `DeterministicAdapter` (default, network-free, `is_live=False`),
   `HttpLlmBoundary` (Anthropic Messages shape; `ProviderUnavailable` without a
   key; never verified), `LlmClient` (pre-flight per-call token ceiling,
   `RunBudget`, timeout, cancellation, transient-only retry, `AuditEvent` per
   attempt — prompt sha256 not raw). `SM_LLM_*` / `SM_AGENT_*` config.
2. ✅ **CI-VERIFIED (run `34429715242`).** Tool framework + evidence/context
   builder (`sm_ai.tools` / `.registry` / `.sanitize` / `.evidence` / `.prompt`).
   `Tool` / `FunctionTool` (explicit Pydantic `args_model`; optional
   `required_permission`; input + output validation). `ToolRegistry` deny-by-
   default: `specs_for(principal)` offers only authorized tools; `invoke`
   re-checks existence → `has_permission` (**the LLM asking is irrelevant**) →
   args → output, emitting a `ToolInvocationRecord` on every path.
   `scan_for_injection` + `fence_untrusted`. `EvidenceBuilder` (trusted plain,
   everything else fenced as data, size cap → `ContextPoisoningDetected`).
   `build_grounded_messages` **keeps evidence out of the system turn**.
3. ✅ `services/ai-analyst` (port 8010, HTTP-only, no DB / no Kafka) — grounded
   incident summarization / triage / reasoning / remediation *recommendations*.
   `IncidentAnalyst.explain` builds the evidence bundle, runs
   `build_grounded_messages` + `LlmClient`, **validates every `[ref]` the summary
   cites is a real evidence ref** (one repair attempt), else falls back. No LLM
   key / provider outage / ungrounded output / oversized context → a
   deterministic factual template with `degraded=true` + a `degraded_reason`.
   Holds **no tools**, takes **no action**; `recommendations` are a fixed vetted
   per-subject list, never model-authored. `sm_contracts` `ExplainRequest` /
   `Explanation` / `EvidenceRef`. `api-gateway`
   `GET /api/v1/soc/detections/{id}/explanation` gathers the evidence
   (tenant-scoped, from the detection record) and proxies via
   `InternalServiceClient.explain` (audience `ai-analyst`); a dependency outage
   → 503. `SM_AI_ANALYST_URL`. `ai-analyst` wired into `Dockerfile.app` / compose
   (`detect` profile, port 8010) / CI (mypy tree + 3 installs + image import).
   **CI-VERIFIED (run `34430968254`).**
4. ✅ **CI-VERIFIED (run `34432159191`) — closes Phase 10.** Multi-agent
   orchestration — `sm_ai.agents`: `AgentSpec` (name + fixed
   system prompt + tool allow-list), `run_agent` under `AgentLimits`
   (`max_steps` / `max_tool_calls` / `wall_clock_s` / cumulative-token
   `RunBudget`) + a cancellation `Event`. `DETECTION_AGENT` / `THREAT_INTEL_AGENT`
   / `RESPONSE_AGENT`. An agent **cannot spawn another agent**, **cannot execute**
   anything, holds **no standing permissions**; an unauthorised or
   out-of-allow-list tool call is refused mid-run without stopping the run; a
   tool exception is a tool result, not a crash. `RESPONSE_AGENT` emits
   `ProposedAction`s; `action_gate(...)` returns `denied` under the shipped
   `SM_RESPONSE_MODE=suggest_only` + `SM_RESPONSE_APPROVAL_REQUIRED=true`, and
   `allowed` is unreachable without production + a signed policy + a reversible
   action. `sm_contracts` `AgentRunRequest` / `AgentRunResult` / `AgentFinding` /
   `ProposedActionOut`. `services/ai-analyst` `POST /api/v1/agents/run`. Local:
   ruff + `mypy --strict` clean (303 files), **658 unit tests** (18 new) +
   `gen_contracts --check`, `test_soc_reads_pg.py` 4 pass real PG,
   `Dockerfile.app` builds + imports. Phase 10 exit report + §23 +
   `REQUIREMENTS_TRACEABILITY` R14 / R29 / R30 / R31 → IMPLEMENTED (with the
   no-live-provider / no-orchestrator-service / no-execution deviations spelled
   out) + `CONTRACTS.md` §7.4 / §7.5 / §7.6.

**PHASE 10 is CLOSED — CI-VERIFIED, final run `34432159191` (all five jobs).**

Exit next action after Phase 10: **PHASE 11 — Threat Hunting + Natural Language
Querying** (prompt not yet given — do NOT start speculatively; the next session
resumes here).

**PHASE 9 — ENTERPRISE SOC DASHBOARD. Unit 1 details — `api-gateway` SOC BFF.**
Tenant-scoped Postgres reads (`SqlSocRepository`: detections / alerts /
threat-scores / summary / MITRE heatmap / entity timeline, keyset-paged) + minted-JWT
proxies to `correlation-engine` / `graph-service` / `threat-intel-service` /
`mitre-service` (`InternalServiceClient`). `GET /api/v1/soc/*` — every route
`require_permission(detections:read | hunt:query)`, tenant from the session
`Principal`, a dependency outage → 503. `sm_contracts.api.soc` + `CursorPage[…]`
schema exports for the generated TS client. `SM_GRAPH_SERVICE_URL`. Local
gauntlet green — ruff, `mypy --strict`, 578 unit tests (12 new SOC tests) +
`gen_contracts --check`, 4 real-PG integration tests (`test_soc_reads_pg.py`),
`Dockerfile.app` build. **Commit Unit 1, push, confirm CI green.**

**Then Unit 2 — `frontend/web` scaffold + typed client + auth shell.** Next.js
(App Router) + TypeScript. `packages/contracts-ts` generates the TS types from
the committed JSON Schema (`npm install json-schema-to-typescript` under
`packages/contracts-ts`, then `gen_contracts.py` emits `src/*.ts`); a thin typed
`fetch` client wraps the `/api/v1/*` surface — the frontend **never re-declares a
backend shape**. Auth: login form → `POST /api/v1/auth/login` → session cookie;
a route guard redirects unauthenticated users; `/me` drives the tenant-aware
shell (nav, user menu, theme). Loading / error / empty-state primitives.
Security: no token in JS-readable storage (httpOnly cookie), CSP, `dangerouslySetInnerHTML`
banned by lint, no secret in the bundle. A **new `frontend` CI job**: `npm ci`,
`npm run lint`, `npm run typecheck`, `npm run build`, `npm test` (vitest +
testing-library). Component + auth-guard tests.

**Then Unit 3 — the SOC views:** dashboard (summary counters + risk list + recent
alerts), alerts list + detail, incidents, attack-chain list + detail (stage
timeline), MITRE ATT&CK view (heatmap), risk heatmap, entity explorer, threat-intel
view. Typed data hooks, every view has loading / error / empty states, severity
is colour + text + icon (a11y). Demo/seed data, if any, is labelled in the UI.
Tests: component, API-contract (the generated types match a fixture response),
critical-flow (login → dashboard → open an alert).

**Then Unit 4 — attack graph + timeline + real-time + polish + close:** Cytoscape
attack-graph view with node/edge navigation and a detail panel; an entity/chain
timeline; live updates where supported (SSE/poll — `graph.events` / `detections`
are Kafka, so the gateway needs a projection or a poll fallback — poll for v1,
documented); responsive + keyboard-navigable; graph-interaction tests. Phase 9
exit report + §23 + `REQUIREMENTS_TRACEABILITY` R13 + `CONTRACTS.md`.

**PHASE 8 — GNN + TEMPORAL INTELLIGENCE. COMPLETE / CI-VERIFIED** (all four jobs,
runs `34408045416` / `34408494057` / `34409131977` / `34410178417`). Units 1–4.
Unit 1 (`sm_ml.graph`)
CI-green (run `34408045416`); Unit 2 (`sm_ml.temporal`) CI-green (run
`34408494057`); Unit 3 (`services/ml-training`) CI-green (run `34409131977`).
Unit 4 (serving + intel + close): `ml-inference` `POST /api/v1/infer/graph/{model}`
(structural builtin; GNN → 503 `MODEL_UNAVAILABLE`; malformed graph → 422),
`graph-service` `GET /api/v1/graph/intel`, `sm-ml` added to `graph-service`.
Local gauntlet green — ruff, `mypy --strict` over 14 src trees (268 files), 568
unit tests + `gen_contracts --check`, real-Neo4j `test_graph_intel_neo4j.py`,
`Dockerfile.app` build + entrypoint import. Phase 8 exit report + §23 + R11 / R12
→ IMPLEMENTED (library, no benchmark verified), R15 → FOUNDATION IMPLEMENTED +
`CONTRACTS.md` "Phase 8 closed". **Commit Unit 4, push, confirm CI green → closes
Phase 8.**

**Then Unit 3 — `services/ml-training`:** the reproducible pipeline
`dataset → preprocessing → graph construction → feature generation → training →
validation → checkpoint → model version → inference → evaluation` as a real
CLI + pydantic config with seeds / model metadata / artifact handling. Runs
end to end on a labelled synthetic fixture graph to prove the plumbing and writes
an artifact whose `metadata.json` carries `metrics: NOT VERIFIED — REQUIRES
DATASET/TRAINING EXECUTION`. Tests: pipeline stages, determinism, artifact
handling, model loading.

**Then Unit 4 — serving + failure behaviour + close:** `ml-inference` serves the
GNN graph models (`POST /api/v1/infer/graph/{model}`; missing / unloadable → 503
`MODEL_UNAVAILABLE`, structural fallback documented); a `graph-intel` capability
(a periodic scorer over the Neo4j graph, or folded into `correlation-engine`)
emits findings; failure tests (model can't load → fail safe, observable error, no
crash of unrelated services). Phase 8 exit report + §23 + `REQUIREMENTS_TRACEABILITY`
R11–R13 (GNN / temporal / predictive) + `CONTRACTS.md`.

Exit next action after Phase 8: **PHASE 9 — ENTERPRISE SOC DASHBOARD**
(prompt already given).
ML intelligence layer (GraphSAGE / GAT / graph anomaly detection / suspicious
subgraph classification / threat-cluster discovery / temporal analysis /
historical replay / cross-session stitching / predictive-attacker-modeling
foundation). Reproducible pipeline `dataset → preprocessing → graph construction
→ feature generation → training → validation → checkpoint → model version →
inference → evaluation` with defined seeds / config / model metadata / feature +
output schema / versioning / artifact handling. Temporal engine: event timeline,
temporal graph state, attack progression, replay, cross-session correlation;
handle out-of-order / missing / clock-skew / duplicate events. Model-load failure
→ fail safely + observable error + documented degraded behaviour, don't crash
unrelated services. **Do not fabricate metrics** — no dataset / trained weights
ship (ADR-024), so evaluation numbers are `NOT VERIFIED — REQUIRES
DATASET/TRAINING EXECUTION`.
After Phase 8: **PHASE 9 — ENTERPRISE SOC DASHBOARD**, then **PHASE 10 — AI
SECURITY ANALYST + MULTI-AGENT DEFENSE**, then Phase 11 (Threat Hunting + NL
querying — prompt not yet given).

Exit next action after Phase 5: **PHASE 6 — THREAT INTELLIGENCE + MITRE ATT&CK**
(user pastes the prompt; do not start speculatively).

### Standing debt carried past Phase 2

- Topics are now provisioned by `ensure_topics` — the compose `topics-init`
  one-shot and the CI `integration` job's "Provision Kafka topics" step both
  run `scripts/provision_topics.py` before any consumer/producer starts (and an
  under-provisioned auto-created topic is grown). A real deployment still runs
  its own IaC.
- The `ingestion-gateway` per-IP rate limiter is a placeholder; per-sensor
  quota (keyed on the resolved `SensorIdentity`, after auth) is the intended
  design and is deferred to a later unit.
- `last_seen_at` is touched on every authenticated ingest (throttled to 1/min
  per sensor). Revisit if sensor counts get large — a batched async update
  would remove the write from the hot path.

### Superseded plan for Phase 1 Unit 6 (kept for the record)

**PHASE 1, Unit 6 (remaining) — close out Phase 1.** Blocked until Docker is
available, by either route (`make up` + `make test-integration`, or push to
GitHub). Then: record the real output, fix first-run failures, add the
end-to-end OIDC sign-in, and promote traceability statuses to
`INTEGRATION VERIFIED` only for what the run proves.

### Superseded plan for Unit 5 (kept for the record — AUTHORED, NOT EXECUTED)

- `deploy/docker/docker-compose.yml`: `postgres:16`, `redis:7`,
  `quay.io/keycloak/keycloak` (dev realm `sentinelmesh`), `prom/prometheus`,
  `grafana/grafana`, and the `app` (api-gateway) built from
  `deploy/docker/Dockerfile.app`. Neo4j / Redpanda / MinIO / MLflow are declared
  but not required until their phase. Healthchecks plus
  `depends_on: condition: service_healthy`. **Container-to-container addressing
  uses service names** (`SM_PG_HOST=postgres`, `SM_REDIS_URL=redis://redis:6379/0`,
  `SM_OIDC_ISSUER=http://keycloak:8080/realms/sentinelmesh`), never `localhost`.
  Named volumes for postgres/redis data, git-ignored.
- `deploy/docker/Dockerfile.app`: multi-stage, non-root user, installs the three
  packages, entrypoint `python -m sm_api_gateway`.
- A Keycloak realm import file for the dev IdP (`sentinelmesh` realm, the
  `sentinelmesh-api` confidential client, one test user).
- `deploy/prometheus/prometheus.yml` scraping the gateway.
- **Then run the integration work this unlocks** (the first non-offline
  verification in the project):
  - `alembic -c migrations/postgres/alembic.ini upgrade head`, then
    `downgrade base`, then `upgrade head` against the compose Postgres.
  - `tests/integration/`: `AuditWriter` chain continuity and the per-tenant
    advisory lock under concurrent appends; the append-only trigger rejecting
    UPDATE/DELETE; model constraints (unique email per tenant, lowercase-email
    check, role partial unique indexes); `SqlUserRepository` /
    `SqlRoleRepository` behaviour including the tenant predicate; the Redis
    session store TTL/absolute-expiry behaviour.
  - Mark them `integration` and skip cleanly when Docker is unavailable.
- Record in this file exactly which previously-`NOT VERIFIED` items became
  verified, with the commands and their real output.

Then **Unit 6** = end-to-end Phase-1 tests through the running stack (real
login against Keycloak), `Makefile`/`justfile` targets, CI wiring, and the
documentation promotion listed in step 7 below.

### Superseded plan for Unit 4 (kept for the record — DONE)

- `services/api-gateway/pyproject.toml` (depends on `sm-contracts`, `sm-common`,
  `fastapi`, `uvicorn`), `src/sm_api_gateway/`.
- `app.py`: FastAPI factory — `configure_logging`, `configure_tracing`,
  `RequestContextMiddleware`, `SecurityHeadersMiddleware`,
  `BodySizeLimitMiddleware`, `CORSMiddleware` from `build_cors_kwargs`,
  `install_exception_handlers`, lifespan wiring `Database`/`Cache`/`OidcClient`
  and disposing them on shutdown.
- `routes/health.py`: `/healthz` (`liveness`), `/readyz`
  (`evaluate_readiness` over `probe_check(Database)` + `probe_check(Cache)`),
  `/health/deps` (requires `ops:read`), `/api/v1/meta`.
- `security/principal.py`: `Principal` (user id, tenant id, roles, permission
  set) resolved **server-side** from the session; `get_current_principal`
  dependency; `require_permission(code)` dependency that is deny-by-default and
  records `authz_denials` metric + audit entry.
- `security/session.py`: Redis-backed session store (idle + absolute expiry
  from config), httpOnly/Secure/SameSite cookie, CSRF double-submit token.
- `repositories/`: tenant-scoped repositories over `sm_common.db.models`. The
  tenant predicate is injected from `Principal` — no function accepts a caller
  supplied `tenant_id`.
- `routes/auth.py`: `POST /api/v1/auth/login` (Argon2id, `dummy_verify` for
  unknown users, lockout via `failed_login_count`/`locked_until`, generic error,
  audit on success and failure), `GET /api/v1/auth/oidc/login`,
  `GET /api/v1/auth/oidc/callback` (state + PKCE + nonce validated),
  `POST /api/v1/auth/logout`, `GET /api/v1/me`.
- `routes/admin.py`: `GET /api/v1/admin/users` (cursor-paginated),
  `POST /api/v1/admin/users`, `GET /api/v1/admin/roles`,
  `POST /api/v1/admin/users/{id}/roles` (audited). Responses use
  `sm_contracts.api` models only — never an ORM object.
- Tests: login success / invalid / lockout; permission enforcement per route;
  **cross-tenant isolation** (list, detail, role-grant must not reveal another
  tenant's data); invalid payload → canonical error; `/readyz` degraded when a
  dependency probe fails. Anything needing a live Postgres/Redis is marked
  `integration` and skipped until Unit 5 provides docker-compose.

Then **Unit 5** = `deploy/docker` (compose brings the first real Postgres/Redis
and unblocks the integration tests, including applying the migrations).
**Unit 6** = end-to-end Phase-1 tests + `Makefile`/CI + doc promotion.

### Superseded plan for Unit 3 (kept for the record — DONE)

- `packages/common-py/src/sm_common/db/models.py`: SQLAlchemy 2 declarative
  models for the Phase-1 tables (`Tenant`, `User`, `Role`, `Permission`,
  `UserRole`, `RolePermission`, `Sensor`, `AuditLog`) — UUIDv7 PKs,
  `tenant_id` FKs, unique/check constraints, indexes, `created_at`/`updated_at`
  (trigger-maintained), `deleted_at` where lifecycle needs it. These models are
  the shared schema; `api-gateway` is the only writer (ADR / service-catalog).
- `sm_common/audit/writer.py`: `AuditWriter` — given an `AsyncSession`, reads the
  tenant's last chain hash `... FOR UPDATE`, computes `compute_entry_hash`,
  inserts the row in the caller's transaction. For response-critical actions the
  audit insert shares the action's transaction.
- `migrations/postgres/`: `alembic.ini` + `env.py` (async engine, `target_metadata`
  = models' `MetaData`); migration `0001_initial` (all 8 tables, full
  constraints/indexes, `updated_at` trigger function); migration `0002_seed`
  (permission catalog from `PermissionCode`, system roles from `SystemRole`,
  role→permission grants).
- Tests: model constraint round-trips + `AuditWriter` chain continuity **against
  a real Postgres** (docker-compose, `integration` marker — **blocked until
  Docker is installed**); offline: migration `upgrade head` / `downgrade base` /
  `upgrade head` on SQLite-incompatible? use a Postgres testcontainer or skip —
  decide in Unit 3; Alembic script lints (`alembic check`).

Then **Unit 4** = `services/api-gateway`. **Unit 5** = `deploy/docker`
(compose brings the first real Postgres/Redis — unblocks the integration tests).
**Unit 6** = end-to-end Phase-1 tests + `Makefile`/CI + doc promotion.

Original Phase-1 step list (for reference):

1. ~~`packages/common-py` config/logging/errors/IDs/security/health/FastAPI~~ —
   **DONE (Unit 1).**
1b. ~~`packages/common-py` DB engine/session/transaction, Redis client, OIDC
   client, OTel + Prometheus, audit hash-chain primitives~~ — **DONE (Unit 2).**
2. `migrations/postgres`: init Alembic; `0001` = Phase-1 tables
   (`tenant`, `user`, `role`, `permission`, `user_role`, `role_permission`,
   `sensor`, `audit_log`) — full PK/FK/unique/check/index + `updated_at` trigger;
   `0002` seed = permission catalog (`PermissionCode`) + system roles
   (`SystemRole`) + role→permission grants. CI runs `upgrade head` /
   `downgrade base` / `upgrade head` on a scratch DB.
3. `services/api-gateway`: FastAPI app; `/healthz`, `/readyz`, `/health/deps`,
   `/api/v1/meta`; local login (`/api/v1/auth/login` — Argon2id, lockout,
   constant-time, no user enumeration); OIDC login + callback; logout; session
   cookie (httpOnly/Secure/SameSite) + Redis session store + CSRF token;
   `get_current_principal` dependency; `require_permission(...)` dependency
   (deny-by-default); tenant-scoped repository layer (injected predicate, never
   client-supplied); `/api/v1/me`; `/api/v1/admin/users` (list paginated,
   create) + `/api/v1/admin/roles` (list) + `/api/v1/admin/users/{id}/roles`
   (grant, audited); HTTP hardening (body cap, timeout, CORS allow-list with
   prod-wildcard rejection, security headers, per-route rate limit). Responses
   use `sm_contracts.api` models only — no ORM objects.
4. `deploy/docker`: `Dockerfile.app`, `docker-compose.yml` (postgres, redis,
   keycloak, prometheus, grafana, app) — service-name networking, health gating.
5. Tests (`tests/` + per-package): config validation; Argon2id hash/verify;
   login success / lockout / invalid credentials; permission enforcement;
   **cross-tenant isolation** (list / detail / role-grant must 403/404);
   invalid payload → canonical error shape; migration up/down/up on a scratch
   DB; health / readiness behavior. Integration tests use compose Postgres/Redis
   (real infra, not mocked).
6. Tooling: per-service `pyproject.toml`; `Makefile`/`justfile`
   (`setup`, `migrate`, `run`, `test`, `lint`, `typecheck`, `fmt`); wire
   `ruff` + `mypy --strict` + `pytest` in CI.
7. Docs: update this file; `CONTRACTS.md` (promote Phase-1 API/entity contracts
   DRAFT → STABLE); `REQUIREMENTS_TRACEABILITY.md` (R1 `sensor` model, R23
   health/logging/request-IDs, R38 auth/RBAC/SSO foundation →
   PARTIALLY IMPLEMENTED / LOCALLY VERIFIED as actually verified).

## Change log

| Date | Phase | Change |
|---|---|---|
| 2026-09-09 | 1 (Unit 6 — integration) | Docker Desktop installed on the dev machine (engine 29.7.2, WSL2 2.5.10). First non-offline verification: **52 integration tests pass** against real PostgreSQL 16 + Redis 7; full `docker compose` stack (postgres/redis/migrate/app) comes up, migrations apply `0001 -> 0002`, `/healthz` + `/readyz` + `/api/v1/meta` green; image builds, runs as uid 10001, rejects a prod CORS wildcard. Four first-run defects fixed: (1) audit hash chain forked under concurrency — added DB-assigned `audit_log.seq` identity column as the canonical chain order, `_last_hash` orders by it; (2) migration `0002` downgrade broken under asyncpg (`ANY(:ids::uuid[])`) — rewritten with typed `.in_()`; (3) session-scoped integration fixtures clashed with pytest-asyncio per-test loops — made function-scoped; (4) `test_head_is_the_expected_revision` asserted against an un-upgraded DB — uses `alembic heads`. Non-integration suite 189 passed, mypy --strict clean (69 files), ruff clean. Branch renamed `master -> main`. Remaining: the CI `integration`/`image` jobs (need remote + `gh auth login`). |
| 2026-09-08 | 0 | Repo created at `C:\Users\gmalh\sentinelmesh`; skeleton + doc set; ADR-001…024; all 38 requirements traced. Commit `0b91ed2`. Status: NOT LOCKED. |
| 2026-09-08 | 0 (close) | `packages/contracts-py` implemented (envelope, error contract, Phase-1 entities + APIs, enums); `scripts/gen_contracts.py` + `packages/contracts-ts` schemas; consistency-review pass (2 fixes). Verified: pytest 19 passed, mypy --strict clean, ruff clean, codegen + `--check` pass. **Architecture status: LOCKED.** |
| 2026-09-08 | 1 (Unit 1) | `packages/common-py` platform primitives: `config` (typed `AppSettings`, startup validation, production guards), `logging` (structlog JSON + redaction), `redaction`, `context`, `ids` (uuid7), `clock`, `errors` (`SmError` → canonical `ErrorResponse`), `security.passwords` (Argon2id + dummy-verify), `security.jwt_internal` (mint/verify + rotation), `observability.health`, `fastapi` (request-context middleware, exception handlers, security headers, body-size limit, CORS builder). Verified: **pytest 64 passed** (19+45), mypy --strict clean (17 files), ruff clean. Root pytest `--import-mode=importlib`; ruff `line-length=120`, `**/errors.py` N818 ignore. |
| 2026-09-08 | 1 (Unit 2) | `packages/common-py` infra clients: `db` (async SQLAlchemy 2 engine, `Database` session/`transaction()`/`ping`), `cache.redis` (`Cache` + key prefix + `ping`), `security.oidc` (`OidcClient` — discovery cache, PKCE `S256`, auth URL, code exchange, ID-token verify via `PyJWKClient`+`anyio.to_thread`), `observability.metrics` (`Metrics` + per-process registry), `observability.tracing` (OTLP bootstrap, no-op without endpoint), `audit.hashing` (per-tenant hash chain primitives). Verified: **pytest 81 passed** (19+62), mypy --strict clean (27 files), ruff clean. Deps added: sqlalchemy[asyncio], asyncpg, redis, prometheus-client, opentelemetry-sdk + otlp-http, httpx, anyio; dev respx. |
| 2026-09-09 | 1 (Unit 6 + review) | Fixed-window `RateLimitMiddleware` on the api-gateway (keyed on the resolved client IP, fails open with `sm_rate_limiter_errors_total`, health/metrics exempt, 429 in the canonical shape). Pre-output §23 review: 7 defects found and fixed in never-run code (login-lockout double count — red/green; 403->500 on audit failure; spoofable client IP; zeroed 413 request_id; possible duplicate response-start; int4 audit lock; rate limiting unwired). Six-role sign-off recorded. CI workflow schema hardened; `scripts/push_and_watch.sh` added. Verified: **pytest 189 passed / 49 skipped**, mypy --strict clean (69 files), ruff clean. **Phase 1 exits IMPLEMENTED / LOCALLY VERIFIED; INTEGRATION NOT VERIFIED — 49 tests, image build and CI all still blocked on Docker/remote.** Commits `5f29957`, `6e5becc`, `806285c`, `9843924`, `901d9c1`, `cbe3462`. |
| 2026-09-09 | 1 (review) | Pre-output engineering review (§23) of Phase-1 code while the integration run stays blocked: 6 defects found and fixed with regression tests — login-lockout double count (proven red/green), a 403 masked as 500 on audit failure, a spoofable client IP, a zeroed request_id in the 413 body, a possible duplicate `http.response.start`, and an int4 audit advisory lock. Verified: **pytest 184 passed / 49 skipped**, mypy --strict clean (68 files), ruff clean. Commits `5f29957`, `6e5becc`. |
| 2026-09-08 | 1 (Unit 6, partial) | `.github/workflows/ci.yml` (static / unit / integration with postgres+redis service containers / image build with non-root and production-config-guard assertions); `SM_REQUIRE_INTEGRATION=1` makes an unreachable dependency a failure rather than a skip, so CI cannot go green on a missing database; 14 offline CI-config checks; `README.md` rewritten with real status and setup. Verified: **pytest 172 passed / 49 skipped**, ruff clean, and the skip-guard exercised directly (11 skipped vs 11 errors). **Workflow never run; no image built; 49 integration tests still unexecuted.** |
| 2026-09-08 | 1 (Unit 5) | `deploy/docker` compose stack (core: postgres/redis/migrate/app; profiles: oidc/obs/graph/bus/objects), multi-stage non-root `Dockerfile.app`, Keycloak dev realm (confidential client, PKCE S256, password grant off), Prometheus config, `.dockerignore`, `Makefile`, `/metrics` route, 49 integration tests and 15 offline deployment-config checks. Verified: **pytest 158 passed / 49 skipped**, mypy --strict clean (67 files), ruff clean. **Docker not installed — no image built, no container started, zero integration tests executed.** |
| 2026-09-08 | 1 (Unit 4) | `services/api-gateway`: app factory + hardening stack, `/healthz` `/readyz` `/health/deps` `/api/v1/meta`, Redis-backed sessions + CSRF double-submit, `get_principal` (privileges re-resolved per request), deny-by-default `require_permission` with metered + audited denials, tenant-scoped repositories, Argon2id local login with lockout and no enumeration/timing oracle, OIDC authorization-code + PKCE + state + nonce with no auto-provisioning, `/me`, audited admin user/role routes, explicit ORM→contract mappers. Verified: **pytest 143 passed**, mypy --strict clean (66 files), ruff clean. **No real Postgres/Redis/OIDC yet.** |
| 2026-09-08 | 1 (Unit 3) | `sm_common.db.base`/`models` (8 Phase-1 tables, UUIDv7 PKs, enum CHECKs rendered from `sm_contracts`, role partial unique indexes, security state kept out of contracts); `sm_common.audit.writer.AuditWriter` (per-tenant advisory lock, hash chain, runs in caller's transaction); `migrations/postgres` (alembic.ini + async env.py + `0001_initial` with `updated_at` and append-only audit triggers + `0002_seed_rbac` with 14 permissions / 5 system roles / grants, uuid5-derived ids). Verified: **pytest 102 passed**, mypy --strict clean (30 files), ruff clean, `alembic upgrade head --sql` emits full DDL offline. **Migrations never applied to a real database** (no Docker). Dep added: alembic 1.19.2. |
