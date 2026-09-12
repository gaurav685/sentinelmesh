# SentinelMesh

AI-native cybersecurity threat detection and attack-intelligence platform.

SentinelMesh ingests security telemetry (network flows, authentication logs, DNS
events, process/endpoint events, file-access events), normalizes and enriches it
into a canonical event stream, builds a dynamic attack graph, runs anomaly and
graph-ML detection, reconstructs attack chains, maps them to MITRE ATT&CK, scores
threats, and drives an analyst-facing SOC experience with LLM-assisted
explanation, natural-language hunting, safe attack simulation, deception, a
security digital twin, threat memory + predictive intelligence, attack-story
reporting, full observability/benchmarking, and a production Kubernetes/Helm
deployment.

This repository is built phase by phase under a strict engineering constitution
([`CLAUDE.md`](CLAUDE.md)). No phase begins before the previous one is complete
and its CI is green on a clean runner. No performance, benchmark, deployment, or
ML-accuracy claim appears anywhere in this repository unless it was actually
measured and the evidence is recorded.

## Status

**Phases 0–16 complete and CI-verified. Phase 17 (Testing + CI/CD + Security
Hardening) has been named as the next phase but its full prompt has not yet
been given — do not start it, and do not invent a Phase 18 or beyond. Wait
for the exact prompt.**

| Phase | Scope | State |
|---|---|---|
| 0 | Architecture discovery + lock | complete |
| 1 | Foundation: config, database, authentication, RBAC | complete — CI green |
| 2 | Telemetry ingestion + normalization | complete — CI green |
| 3 | Kafka event bus + stream processing | complete — CI green |
| 4 | Neo4j attack graph + graph intelligence | complete — CI green |
| 5 | ML detection (anomaly + rule-based) | complete — CI green |
| 6 | Threat intelligence + MITRE ATT&CK mapping | complete — CI green |
| 7 | Attack-chain correlation + threat scoring | complete — CI green |
| 8 | Graph-model serving + live intel endpoint | complete — CI green |
| 9 | SOC frontend: attack graph, realtime polish | complete — CI green |
| 10 | AI analyst: grounded LLM explanations + guarded agents | complete — CI green |
| 11 | Natural-language threat hunting | complete — CI green |
| 12 | Simulation + deception + security digital twin | complete — CI green |
| 13 | Threat memory + predictive intelligence | complete — CI green |
| 14 | Reporting + attack storytelling | complete — CI green |
| 15 | Observability + benchmarking + evaluation | complete — CI green |
| 16 | Kubernetes + enterprise deployment | complete — CI green (see caveat below) |
| 17 | Testing + CI/CD + security hardening | **named, prompt not yet given — not started** |

`docs/IMPLEMENTATION_STATE.md` is authoritative for exactly where the build is
and what the next action is. It carries one exit report per phase, each with
its own delivered/verification/deferred/exit-criteria breakdown — read it
before touching anything.

**Phase 16 caveat, stated plainly so it is never lost:** the Helm chart and a
real local `kind` cluster were built and verified — all 6 self-hosted
stateful components (Postgres, Neo4j, Redis, Redpanda, MinIO, Keycloak) and
all 14 real app services reached genuine `1/1 Running` against real
dependencies, with three real image/security-context bugs found and fixed by
actually running them. One thing was **not** resolved: a short-lived one-off
pod's database-migration connection to Postgres repeatedly failed/timed out
in that specific local `kind` environment, while a long-lived service
connecting through the identical code path worked fine — root cause not
conclusively isolated despite substantial investigation. This is documented
honestly as `NOT VERIFIED — REQUIRES FURTHER INVESTIGATION` in
`docs/architecture/kubernetes-deployment.md`, not hidden or claimed fixed.
Anyone picking this up should read that section before trusting a real
cluster rollout.

### What exists and runs today

- **`packages/contracts-py`** — the canonical event envelope, the API error
  contract, telemetry payloads, the graph-command contract, the Kafka topic
  registry, the Neo4j label/relationship allowlist, and every request/response
  shape for hunting, the AI analyst, agents, simulation, deception, threat
  memory, predictive intelligence, reporting, and benchmarking. JSON Schema
  (and generated TypeScript) for the frontend is built from these models.
- **`packages/common-py`** — typed configuration with production fail-fast
  guards, structured logging with secret redaction, request/correlation IDs,
  Argon2id passwords, internal service JWTs, an OIDC client, Postgres / Redis /
  Kafka / Neo4j clients, the at-least-once consumer + retry/DLQ processor,
  real OpenTelemetry tracing (`TracingMiddleware`, W3C context propagation,
  Kafka-consumer spans), real HTTP + DB-pool + Neo4j-query metrics,
  health/readiness/liveness/dependency checks, and the audit hash chain.
- **`packages/ml-py`** — the graph-anomaly / temporal / GNN-serving library,
  the security digital twin (assets, relationships, weaknesses, attack paths,
  blast radius, defensive stress testing), and the synthetic attack-scenario
  engine (APT / ransomware / insider / brute-force, deterministic, isolated).
- **`packages/ai-py`** — the LLM provider boundary (deterministic adapter +
  HTTP boundary), an authorized-tool + evidence framework, and a guarded
  multi-agent runner. The LLM is never trusted with standing privilege.
- **`services/ingestion-gateway`** — authenticated sensor telemetry intake,
  per-sensor dedup, batch limits, writes to Kafka `telemetry.raw`.
- **`services/normalization-engine`** — `telemetry.raw` → canonical events on
  `events.canonical`; poison messages to the DLQ; optional threat-intel
  enrichment.
- **`services/stream-processor`** — a stateless stream job that turns canonical
  events into idempotent graph commands on `graph.commands`.
- **`services/graph-service`** — the only write path into Neo4j: consumes
  `graph.commands`, applies each as a parameterized idempotent MERGE (label
  allowlist, `command_id` dedup, out-of-order safe, tenant invariants), emits
  `graph.events`; serves the tenant-scoped graph-query API (`entity` /
  `neighbors` / `paths` / `intel`) and the threat-hunting compiler (a closed
  set of parameterized Cypher templates — natural language never becomes a
  raw query).
- **`services/detection-engine`** — adaptive anomaly detection + stateful rule
  detectors over canonical events, with grounded evidence.
- **`services/mitre-service`** — the imported ATT&CK catalog and technique
  mapping for detections and attack chains.
- **`services/threat-intel-service`** — indicator storage, enrichment,
  freshness/expiry, and (optional, feature-flagged) live provider polling.
- **`services/correlation-engine`** — attack-chain reconstruction and threat
  scoring from correlated detections, with a graph write-back.
- **`services/ml-inference`** — serves the structural graph-anomaly detector
  (always available) and named GNN artifacts (503 when one is missing, never
  a fabricated score).
- **`services/ml-training`** — offline training/artifact tooling, plus the
  reproducible benchmark harness (`sm_ml_training.benchmark`): dataset
  adapters, stdlib-only metrics, real executed runs against NSL-KDD (a
  statistical baseline and an Isolation Forest comparison), never a claimed
  number until the benchmark actually ran.
- **`services/ai-analyst`** — grounded LLM explanations (evidence-only
  prompting, prompt-injection resistant), the natural-language hunt planner
  (LLM → closed `QueryPlan` schema only, never raw Cypher), and a guarded
  multi-agent runner with no standing privilege.
- **`services/simulation-service`** — runs the four synthetic attack
  templates against a seeded, isolated environment (never a real system);
  optionally feeds the real detection pipeline with events labelled
  `simulated`; hosts the deception decoy registry (isolated network
  boundaries only — `production` is not a legal value at the schema **or**
  the database level; no credential field; one-way interaction capture;
  idempotent teardown); serves the digital twin and blast-radius analysis.
- **`services/memory-service`** — threat memory: pgvector similarity search
  over past incidents/detections, deterministic heuristic predictive-intel
  scoring — never fabricated, never presented as fact, always labelled as a
  prediction with its basis.
- **`services/reporting-service`** — attack-storytelling and report
  generation; every narrative distinguishes evidence, inference, prediction,
  and synthetic (simulation) content explicitly; secure S3 export with
  path-traversal-safe key handling.
- **`services/api-gateway`** — local + OIDC authentication, server-side
  sessions, CSRF, deny-by-default RBAC, tenant-scoped reads, audited admin
  routes, and the SOC BFF proxy for graph, hunting, the AI analyst,
  simulation/deception, memory/predictions, reporting, and benchmarks.
- **`frontend/web`** — the analyst SOC UI (Next.js): dashboard, alerts,
  incidents, attack chains, MITRE heatmap, entity explorer, attack-graph
  explorer, threat hunting (NL + structured), threat intel, simulation
  (scenario runner + digital twin + blast radius), deception (decoy registry
  + captured interactions), threat memory + predictions, reports, and
  benchmark results — every synthetic view visibly badged "SIMULATION".
- **`migrations/postgres`** — the control-plane schema (Alembic, linear
  history, 15 revisions).
- **`migrations/neo4j`** — versioned Cypher schema (constraints + indexes),
  applied by `scripts/graph_migrate.py`.
- **`deploy/docker`** — the full local stack as one application image, with
  compose profiles for the bus, graph, detection services, OIDC, observability,
  and object storage.
- **`deploy/grafana`** — real provisioned Prometheus datasource + a 14-panel
  dashboard.
- **`deploy/helm/sentinelmesh`** — the production Kubernetes chart: one
  values-driven chart (not 14 near-identical sub-charts) covering
  Deployments/Services/HPA/PDB/NetworkPolicy/ServiceAccounts for every real
  service, self-hosted StatefulSets for every stateful dependency, a
  migration Job, an Ingress, and both an `ExternalSecrets`-backed and a
  dev-only manual secrets path. See `docs/architecture/kubernetes-deployment.md`
  for the full manifest inventory, security posture, scaling strategy,
  backup/recovery documentation, and — importantly — the real verification
  result including what is **not** yet resolved.
- **`deploy/k8s/namespaces`** — the cluster-scoped namespace bootstrap
  (`sentinelmesh-{system,data,bus,app,ml,observability}`), applied once,
  outside the Helm release.

Scaffolded but **not yet built** (empty placeholders, no code, no Kubernetes
resources built for them):
`agent-orchestrator`, `ai-analyst-service` (a stale naming remnant — the real
service is `ai-analyst`), `deception-service` (superseded by
`simulation-service`'s decoy registry), `federation-service`,
`notification-service`.

### Verification

CI runs five jobs on every push and pull request: `static` (ruff +
`mypy --strict` over every package and service), `unit` (unit + contract tests
+ JSON-Schema drift check), `integration` (the marked tests against real
PostgreSQL 16, Redis 7, Redpanda, and Neo4j 5), `image` (build the single
application image for every service, assert non-root, importability, and the
production fail-fast guards), and `frontend` (generated-contract drift check,
lint, vitest, production build).

`SM_REQUIRE_INTEGRATION=1` (set in CI) turns an unreachable dependency into a
failure instead of a skip, so a green `integration` job always means the tests
really ran.

CI does **not** stand up a real Kubernetes cluster (`kind`/`helm` are not CI
dependencies) — the Phase 16 verification described above was performed
locally and its result is recorded in `docs/architecture/
kubernetes-deployment.md` and `docs/IMPLEMENTATION_STATE.md`'s Phase 16 exit
report, not re-run automatically on every push.

Deliberately not implemented yet: a cluster stream engine (Flink) — the stream
jobs so far are stateless and run as plain Python; the decision and its trigger
are recorded in ADR-010. A live LLM provider — every LLM-backed feature (AI
analyst, NL hunting) has a deterministic-adapter path and degrades to an
honest "unsupported" without credentials, never a guess (ADR-014). MLflow
experiment tracking, Loki/Tempo/Jaeger log/trace collectors, KEDA/Kafka-lag
autoscaling, and an ingress controller/frontend image for the Kubernetes chart
— each is documented as deferred with a reason, not silently skipped.

## Documentation

- [`docs/IMPLEMENTATION_STATE.md`](docs/IMPLEMENTATION_STATE.md) — authoritative current state, one exit report per phase, and the exact next action
- [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md) — the ADRs and open questions
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) — API / event / entity / ML / AI contracts, with a changelog
- [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md) — all 38 architecture requirements, mapped to real code and their real verification status
- [`docs/architecture/`](docs/architecture/) — overview, service catalog, data model, event model, security model, failure model, observability, deployment (including `kubernetes-deployment.md`, the Phase 16 detail)
- [`CLAUDE.md`](CLAUDE.md) — the engineering constitution this repository is built under; **read this before writing any code here**

## Continuing this build (for an agent picking this up)

This repository has been built autonomously, phase by phase, by an AI
assistant following `CLAUDE.md`'s Engineering Constitution. If you are an
agent (or a human) continuing this work — including in another tool — the
same rules apply, because the codebase's own consistency depends on them:

1. **Read `docs/IMPLEMENTATION_STATE.md` first**, top to bottom of the
   "Current phase" section, and skim the most recent exit report. It is the
   single source of truth for what is actually done versus merely designed.
2. **Never start a phase whose full prompt has not been given.** A phase name
   being mentioned (e.g. "Phase 17 — Testing + CI/CD + Security Hardening" in
   this README) is not a prompt — it is a pointer. Wait for the actual,
   detailed phase specification before writing code for it. Do not invent
   scope, unit boundaries, or a Phase 18+ that was never named.
3. **Never fabricate.** No performance number, benchmark result, test-passing
   claim, or "verified" status may be stated unless it was actually measured
   or actually run, with the command/evidence recorded. If something can't be
   verified in the current environment, say so explicitly (e.g. `NOT VERIFIED
   — REQUIRES <specific missing thing>`) rather than assuming success.
4. **Standing per-unit workflow, unchanged across every phase so far:**
   implement one coherent unit → run the full local gauntlet (`ruff`,
   `mypy --strict`, unit tests, `python scripts/gen_contracts.py --check`,
   the relevant real-infrastructure integration tests, and a Docker image
   build) → update `docs/IMPLEMENTATION_STATE.md` (and `docs/CONTRACTS.md` /
   `docs/REQUIREMENTS_TRACEABILITY.md` if contracts or requirements moved) →
   commit → push to `main` → poll GitHub Actions CI until it is green on that
   commit → only then move to the next unit. When a phase closes, the next
   phase's Unit 1 may start immediately under the same rules — but only if
   its prompt has actually been given (rule 2).
5. **Prefer real infrastructure over mocks wherever the repo already does.**
   This build repeatedly found real bugs (dead metrics, dead trace IDs, a
   nested Docker bind-mount failure, three real Kubernetes stateful-image
   security-context bugs) specifically because it ran the real thing instead
   of trusting a passing unit test. Keep doing that.
6. **Match the existing style**: no comments explaining *what* code does
   (names should already do that), comments only for non-obvious *why*; no
   speculative abstractions; no backwards-compatibility shims for code that
   can just be changed; typed, `mypy --strict`-clean Python everywhere.

## Getting started

Requires Python 3.11+, Node 22+, and Docker.

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows;  source .venv/bin/activate on POSIX

pip install -e "packages/contracts-py[dev]" \
            -e "packages/common-py[dev]" \
            -e "packages/ml-py[dev]" \
            -e "packages/ai-py[dev]" \
            -e "services/api-gateway[dev]" \
            -e "services/ingestion-gateway[dev]" \
            -e "services/normalization-engine[dev]" \
            -e "services/stream-processor[dev]" \
            -e "services/graph-service[dev]" \
            -e "services/ml-inference[dev]" \
            -e "services/detection-engine[dev]" \
            -e "services/mitre-service[dev]" \
            -e "services/threat-intel-service[dev]" \
            -e "services/correlation-engine[dev]" \
            -e "services/ml-training[dev]" \
            -e "services/ai-analyst[dev]" \
            -e "services/simulation-service[dev]" \
            -e "services/memory-service[dev]" \
            -e "services/reporting-service[dev]"
pip install alembic pyyaml respx ruff mypy

cp .env.example .env
# then set at minimum:
#   SM_PG_PASSWORD, SM_NEO4J_PASSWORD, SM_INTERNAL_JWT_SIGNING_KEY, SM_OIDC_CLIENT_SECRET
```

### Run the checks

```bash
pytest packages services tests -q -m "not integration"
mypy --strict --python-version 3.11 \
     packages/contracts-py/src/sm_contracts \
     packages/common-py/src/sm_common \
     packages/ml-py/src/sm_ml \
     packages/ai-py/src/sm_ai \
     services/ai-analyst/src/sm_ai_analyst \
     services/api-gateway/src/sm_api_gateway \
     services/ingestion-gateway/src/sm_ingestion_gateway \
     services/normalization-engine/src/sm_normalization_engine \
     services/stream-processor/src/sm_stream_processor \
     services/graph-service/src/sm_graph_service \
     services/ml-inference/src/sm_ml_inference \
     services/detection-engine/src/sm_detection_engine \
     services/mitre-service/src/sm_mitre_service \
     services/threat-intel-service/src/sm_ti_service \
     services/correlation-engine/src/sm_correlation_engine \
     services/ml-training/src/sm_ml_training \
     services/simulation-service/src/sm_simulation_service \
     services/memory-service/src/sm_memory_service \
     services/reporting-service/src/sm_reporting_service
ruff check packages services tests migrations scripts
python scripts/gen_contracts.py --check

cd frontend/web && npm ci && npm run lint && npm run test && npm run build
```

`make help` lists the same commands as targets (`make` is not installed on
Windows by default — run the commands directly, or use WSL / Git Bash).

### Run the stack (docker compose — local/dev)

```bash
docker compose -f deploy/docker/docker-compose.yml \
  --profile bus --profile graph --profile detect up -d --build

python scripts/provision_topics.py     # Kafka topic catalog
python scripts/graph_migrate.py        # Neo4j schema     (or: make migrate)

curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

`migrate` brings the Postgres schema to head and exits; `app` will not start
until it succeeds. Profiles (`bus`, `graph`, `detect`, `oidc`, `obs`,
`objects`) and the service-name networking rule:
[`deploy/docker/README.md`](deploy/docker/README.md).

### Run the integration tests

```bash
docker compose -f deploy/docker/docker-compose.yml \
  --profile bus --profile graph up -d postgres redis redpanda neo4j
pytest tests/integration -q -m integration
```

They skip with an actionable message when a service is unreachable. Set
`SM_REQUIRE_INTEGRATION=1` to turn that skip into a failure.

### Deploy to Kubernetes (production — read the caveat above first)

```bash
kubectl apply -f deploy/k8s/namespaces/namespaces.yaml
helm lint deploy/helm/sentinelmesh
helm template sentinelmesh deploy/helm/sentinelmesh          # static render check
helm install sentinelmesh deploy/helm/sentinelmesh \
  -f deploy/helm/sentinelmesh/values-production.yaml         # real production values (author before a real rollout)
```

`deploy/helm/sentinelmesh/values-kind-smoketest.yaml` is the exact override
file used for this repository's own local `kind` verification — a useful
reference for what a resource-constrained single-node smoke test needs
(trimmed replicas/resources, `secretsProvider: manual`, `frontend`/`ingress`
disabled), **not** a production values file. Read
`docs/architecture/kubernetes-deployment.md` in full before a real rollout,
especially its Verification-status section.

## Datasets

Benchmark datasets (NSL-KDD, UNSW-NB15, CTU-13, EMBER, LANL unified host/network)
are staged **outside** this repository at `C:\Sentinel_Mesh` and referenced by
`SM_DATASET_ROOT`. They are never committed. NSL-KDD has real, executed
benchmark runs (Phase 15); CICIDS2017/UNSW-NB15/LANL are present on disk but
not locally usable in labeled form, and no adapter or number exists for them.

## Authoritative sources

1. **PRIMARY** — SentinelMesh Final 38-Point God-Tier Architecture
2. **SECONDARY** — SentinelMesh Complete Elite Blueprint

The 38-point architecture wins any conflict. Every reconciliation is recorded in
`docs/ARCHITECTURE_DECISIONS.md`.
