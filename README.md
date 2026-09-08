# SentinelMesh

AI-native cybersecurity threat detection and attack-intelligence platform.

SentinelMesh ingests security telemetry (network flows, authentication logs, DNS
events, process/endpoint events, file-access events), normalizes and enriches it
into a canonical event stream, builds a dynamic attack graph, runs anomaly and
graph-ML detection, reconstructs attack chains, maps them to MITRE ATT&CK, scores
threats, and drives an analyst-facing SOC experience with LLM-assisted
explanation, hunting, prediction, simulation, and (guarded) autonomous response.

## Status

**Phase 0 complete — architecture LOCKED. Phase 1 (Foundation) in progress.**

| Phase | State |
|---|---|
| 0 — Architecture discovery + lock | complete |
| 1 — Foundation: config, database, authentication | Units 1–5 done, Unit 6 open |
| 2–10, 38 | not started |

What exists and runs today:

- `packages/contracts-py` — canonical event envelope, error contract, Phase-1
  entity and API models; JSON Schema generation for the frontend.
- `packages/common-py` — typed configuration with production guards, structured
  logging with secret redaction, request/correlation IDs, error types, Argon2id
  passwords, internal service JWTs, an OIDC client, Postgres/Redis clients,
  health/metrics/tracing, and the audit hash chain.
- `migrations/postgres` — the eight control-plane tables plus an RBAC seed.
- `services/api-gateway` — authentication (local + OIDC), server-side sessions,
  CSRF, deny-by-default RBAC, tenant-scoped reads, audited admin routes.
- `deploy/docker` — a local stack (authored; see the honesty note below).

**Honesty note.** Nothing has yet run against real infrastructure on the
development machine: Docker is not installed there, so no image has been built,
no container started, and the 49 integration tests are skipped rather than
passed. `docs/IMPLEMENTATION_STATE.md` lists exactly what that leaves unverified.
No performance, benchmark, deployment or ML-accuracy claim appears anywhere in
this repository.

## Documentation

- [`docs/IMPLEMENTATION_STATE.md`](docs/IMPLEMENTATION_STATE.md) — authoritative current state and exact next action
- [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md) — ADR-001…024 and the open questions
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) — API / event / entity / ML / AI contracts
- [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md) — all 38 architecture requirements, mapped
- [`docs/architecture/`](docs/architecture/) — overview, service catalog, data model, event model, security model, failure model, deployment
- [`CLAUDE.md`](CLAUDE.md) — the engineering constitution this repository is built under

## Getting started

Requires Python 3.11+ and (for anything involving real infrastructure) Docker.

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows;  source .venv/bin/activate on POSIX

pip install -e "packages/contracts-py[dev]" \
            -e "packages/common-py[dev]" \
            -e "services/api-gateway[dev]"
pip install alembic pyyaml respx ruff mypy

cp .env.example .env
# then set at minimum:
#   SM_PG_PASSWORD, SM_INTERNAL_JWT_SIGNING_KEY, SM_OIDC_CLIENT_SECRET
```

### Run the checks

```bash
pytest packages services tests -q          # integration tests skip without Docker
mypy --strict --python-version 3.11 \
     packages/contracts-py/src/sm_contracts \
     packages/common-py/src/sm_common \
     services/api-gateway/src/sm_api_gateway
ruff check packages services tests migrations scripts
python scripts/gen_contracts.py --check
```

`make help` lists the same commands as targets (`make` is not installed on
Windows by default — run the commands directly, or use WSL/Git Bash).

### Run the stack

```bash
docker compose -f deploy/docker/docker-compose.yml up -d --build
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

`migrate` brings the schema to head and exits; `app` will not start until it
succeeds. Details, profiles and the service-name networking rule:
[`deploy/docker/README.md`](deploy/docker/README.md).

### Run the integration tests

```bash
docker compose -f deploy/docker/docker-compose.yml up -d postgres redis
pytest tests/integration -q -m integration
```

They skip with an actionable message when the services are unreachable. Set
`SM_REQUIRE_INTEGRATION=1` to turn that skip into a failure — CI does this so a
green build can never mean "the database was missing".

## Datasets

Benchmark datasets (NSL-KDD, UNSW-NB15, CTU-13, EMBER, LANL unified host/network)
are staged **outside** this repository at `C:\Sentinel_Mesh` and referenced by
`SM_DATASET_ROOT`. They are never committed. No benchmark has been run.

## Authoritative sources

1. **PRIMARY** — SentinelMesh Final 38-Point God-Tier Architecture
2. **SECONDARY** — SentinelMesh Complete Elite Blueprint

The 38-point architecture wins any conflict. Every reconciliation is recorded in
`docs/ARCHITECTURE_DECISIONS.md`.
