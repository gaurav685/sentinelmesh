# SentinelMesh

AI-native cybersecurity threat detection and attack-intelligence platform.

SentinelMesh ingests security telemetry (network flows, authentication logs, DNS
events, process/endpoint events, file-access events), normalizes and enriches it
into a canonical event stream, builds a dynamic attack graph, runs anomaly and
graph-ML detection, reconstructs attack chains, maps them to MITRE ATT&CK, scores
threats, and drives an analyst-facing SOC experience with LLM-assisted
explanation, hunting, prediction, simulation, and (guarded) autonomous response.

This repository is built phase by phase under a strict engineering constitution
([`CLAUDE.md`](CLAUDE.md)). No phase begins before the previous one is complete
and its CI is green on a clean runner. No performance, benchmark, deployment, or
ML-accuracy claim appears anywhere in this repository.

## Status

**Phases 0–3 complete and CI-verified. Phase 4 (Neo4j + graph intelligence) in
progress.**

| Phase | Scope | State |
|---|---|---|
| 0 | Architecture discovery + lock | complete |
| 1 | Foundation: config, database, authentication, RBAC | complete — CI green |
| 2 | Telemetry ingestion + normalization | complete — CI green |
| 3 | Kafka event bus + stream processing | complete — CI green |
| 4 | Neo4j attack graph + graph intelligence | in progress — Units 1–2 done |
| 5–10, 38 | detection, chains, scoring, SOC UI, LLM, response, simulation, … | not started |

`docs/IMPLEMENTATION_STATE.md` is authoritative for exactly where the build is
and what the next action is.

### What exists and runs today

- **`packages/contracts-py`** — the canonical event envelope, the API error
  contract, telemetry payloads, the graph-command contract, the Kafka topic
  registry, and the Neo4j label/relationship allowlist. JSON Schema for the
  frontend is generated from these models.
- **`packages/common-py`** — typed configuration with production fail-fast
  guards, structured logging with secret redaction, request/correlation IDs,
  Argon2id passwords, internal service JWTs, an OIDC client, Postgres / Redis /
  Kafka / Neo4j clients, the at-least-once consumer + retry/DLQ processor,
  health / metrics / tracing, and the audit hash chain.
- **`services/ingestion-gateway`** — authenticated sensor telemetry intake,
  per-sensor dedup, batch limits, writes to Kafka `telemetry.raw`.
- **`services/normalization-engine`** — `telemetry.raw` → canonical events on
  `events.canonical`; poison messages to the DLQ.
- **`services/stream-processor`** — a stateless stream job that turns canonical
  events into idempotent graph commands on `graph.commands`.
- **`services/graph-service`** — the only write path into Neo4j: consumes
  `graph.commands`, applies each as a parameterized idempotent MERGE (label
  allowlist, `command_id` dedup, out-of-order safe, tenant invariants), emits
  `graph.events`.
- **`services/api-gateway`** — local + OIDC authentication, server-side sessions,
  CSRF, deny-by-default RBAC, tenant-scoped reads, audited admin routes.
- **`migrations/postgres`** — the control-plane schema (Alembic, linear history).
- **`migrations/neo4j`** — versioned Cypher schema (constraints + indexes),
  applied by `scripts/graph_migrate.py`.
- **`deploy/docker`** — the full local stack (compose profiles for the bus,
  graph, OIDC, observability, and object storage).

### Verification

CI runs four jobs on every push and pull request: `static` (ruff +
`mypy --strict`), `unit` (unit + contract tests + JSON-Schema drift check),
`integration` (the marked tests against real PostgreSQL 16, Redis 7, Redpanda,
and Neo4j 5), and `image` (build the single application image for all services,
assert non-root, importability, and the production fail-fast guards).

`SM_REQUIRE_INTEGRATION=1` (set in CI) turns an unreachable dependency into a
failure instead of a skip, so a green `integration` job always means the tests
really ran.

Deliberately not implemented yet: a cluster stream engine (Flink) — the stream
jobs so far are stateless and run as plain Python; the decision and its trigger
are recorded in ADR-010.

## Documentation

- [`docs/IMPLEMENTATION_STATE.md`](docs/IMPLEMENTATION_STATE.md) — authoritative current state and exact next action
- [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md) — the ADRs and open questions
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) — API / event / entity / ML / AI contracts
- [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md) — all 38 architecture requirements, mapped
- [`docs/architecture/`](docs/architecture/) — overview, service catalog, data model, event model, security model, failure model, observability, deployment
- [`CLAUDE.md`](CLAUDE.md) — the engineering constitution this repository is built under

## Getting started

Requires Python 3.11+ and Docker.

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows;  source .venv/bin/activate on POSIX

pip install -e "packages/contracts-py[dev]" \
            -e "packages/common-py[dev]" \
            -e "services/api-gateway[dev]" \
            -e "services/ingestion-gateway[dev]" \
            -e "services/normalization-engine[dev]" \
            -e "services/stream-processor[dev]"
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
     services/api-gateway/src/sm_api_gateway \
     services/ingestion-gateway/src/sm_ingestion_gateway \
     services/normalization-engine/src/sm_normalization_engine \
     services/stream-processor/src/sm_stream_processor
ruff check packages services tests migrations scripts
python scripts/gen_contracts.py --check
```

`make help` lists the same commands as targets (`make` is not installed on
Windows by default — run the commands directly, or use WSL / Git Bash).

### Run the stack

```bash
docker compose -f deploy/docker/docker-compose.yml \
  --profile bus --profile graph up -d --build

python scripts/provision_topics.py     # Kafka topic catalog
python scripts/graph_migrate.py        # Neo4j schema     (or: make migrate)

curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

`migrate` brings the Postgres schema to head and exits; `app` will not start
until it succeeds. Profiles and the service-name networking rule:
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
