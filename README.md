# SentinelMesh

AI-native cybersecurity threat detection and attack-intelligence platform.

SentinelMesh ingests security telemetry (network flows, authentication logs, DNS
events, process/endpoint events, file-access events), normalizes and enriches it
into a canonical event stream, builds a dynamic attack graph, runs anomaly and
graph-ML detection, reconstructs attack chains, maps them to MITRE ATT&CK, scores
threats, and drives an analyst-facing SOC experience with LLM-assisted
explanation, natural-language hunting, safe attack simulation, deception, and a
security digital twin.

This repository is built phase by phase under a strict engineering constitution
([`CLAUDE.md`](CLAUDE.md)). No phase begins before the previous one is complete
and its CI is green on a clean runner. No performance, benchmark, deployment, or
ML-accuracy claim appears anywhere in this repository.

## Status

**Phases 0–12 complete and CI-verified. Phase 13 (Memory + Predictive
Intelligence) not started — prompt not yet given.**

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
| 13, 38 | memory/predictive intelligence, root-cause, response, federation, … | not started |

`docs/IMPLEMENTATION_STATE.md` is authoritative for exactly where the build is
and what the next action is.

### What exists and runs today

- **`packages/contracts-py`** — the canonical event envelope, the API error
  contract, telemetry payloads, the graph-command contract, the Kafka topic
  registry, the Neo4j label/relationship allowlist, and every request/response
  shape for hunting, the AI analyst, agents, simulation, and deception. JSON
  Schema (and generated TypeScript) for the frontend is built from these models.
- **`packages/common-py`** — typed configuration with production fail-fast
  guards, structured logging with secret redaction, request/correlation IDs,
  Argon2id passwords, internal service JWTs, an OIDC client, Postgres / Redis /
  Kafka / Neo4j clients, the at-least-once consumer + retry/DLQ processor,
  health / metrics / tracing, and the audit hash chain.
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
- **`services/ml-training`** — offline training/artifact tooling for the
  models `ml-inference` serves.
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
- **`services/api-gateway`** — local + OIDC authentication, server-side
  sessions, CSRF, deny-by-default RBAC, tenant-scoped reads, audited admin
  routes, and the SOC BFF proxy for graph, hunting, the AI analyst, and
  simulation/deception.
- **`frontend/web`** — the analyst SOC UI (Next.js): dashboard, alerts,
  incidents, attack chains, MITRE heatmap, entity explorer, attack-graph
  explorer, threat hunting (NL + structured), threat intel, simulation
  (scenario runner + digital twin + blast radius), and deception (decoy
  registry + captured interactions) — every synthetic view visibly badged
  "SIMULATION".
- **`migrations/postgres`** — the control-plane schema (Alembic, linear
  history, 8 revisions).
- **`migrations/neo4j`** — versioned Cypher schema (constraints + indexes),
  applied by `scripts/graph_migrate.py`.
- **`deploy/docker`** — the full local stack as one application image, with
  compose profiles for the bus, graph, detection services, OIDC, observability,
  and object storage.

Scaffolded but **not yet built** (empty placeholders, no code):
`agent-orchestrator`, `deception-service` (superseded by
`simulation-service`), `federation-service`, `memory-service`,
`notification-service`, `reporting-service`.

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

Deliberately not implemented yet: a cluster stream engine (Flink) — the stream
jobs so far are stateless and run as plain Python; the decision and its trigger
are recorded in ADR-010. A live LLM provider — every LLM-backed feature (AI
analyst, NL hunting) has a deterministic-adapter path and degrades to an
honest "unsupported" without credentials, never a guess (ADR-014).

## Documentation

- [`docs/IMPLEMENTATION_STATE.md`](docs/IMPLEMENTATION_STATE.md) — authoritative current state and exact next action
- [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md) — the ADRs and open questions
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) — API / event / entity / ML / AI contracts
- [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md) — all 38 architecture requirements, mapped
- [`docs/architecture/`](docs/architecture/) — overview, service catalog, data model, event model, security model, failure model, observability, deployment
- [`CLAUDE.md`](CLAUDE.md) — the engineering constitution this repository is built under

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
            -e "services/simulation-service[dev]"
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
     services/simulation-service/src/sm_simulation_service
ruff check packages services tests migrations scripts
python scripts/gen_contracts.py --check

cd frontend/web && npm ci && npm run lint && npm run test && npm run build
```

`make help` lists the same commands as targets (`make` is not installed on
Windows by default — run the commands directly, or use WSL / Git Bash).

### Run the stack

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

## Datasets

Benchmark datasets (NSL-KDD, UNSW-NB15, CTU-13, EMBER, LANL unified host/network)
are staged **outside** this repository at `C:\Sentinel_Mesh` and referenced by
`SM_DATASET_ROOT`. They are never committed. No benchmark has been run.

## Authoritative sources

1. **PRIMARY** — SentinelMesh Final 38-Point God-Tier Architecture
2. **SECONDARY** — SentinelMesh Complete Elite Blueprint

The 38-point architecture wins any conflict. Every reconciliation is recorded in
`docs/ARCHITECTURE_DECISIONS.md`.
