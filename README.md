# SentinelMesh

AI-native cybersecurity threat detection and attack-intelligence platform.

SentinelMesh ingests security telemetry (network flows, authentication logs, DNS
events, process/endpoint events, file-access events), normalizes and enriches it
into a canonical event stream, builds a dynamic attack graph, runs anomaly and
graph-ML detection, reconstructs attack chains, maps them to MITRE ATT&CK, scores
threats, and drives an analyst-facing SOC experience with LLM-assisted
explanation, hunting, prediction, simulation, and (guarded) autonomous response.

## Status

**Phase 0 — Architecture Discovery + Architecture Lock (in progress).**

No runtime implementation exists yet. This repository currently contains only
architecture documentation, contracts scaffolding, and the monorepo skeleton.

See:

- [`docs/IMPLEMENTATION_STATE.md`](docs/IMPLEMENTATION_STATE.md) — authoritative current state and exact next action
- [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md) — technology and boundary decisions with rationale
- [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md) — all 38 architecture requirements mapped to subsystems
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) — API / event / entity / ML contracts (populated later in Phase 0)
- [`docs/architecture/`](docs/architecture/) — per-topic architecture documents

## Authoritative sources

1. **PRIMARY** — SentinelMesh Final 38-Point God-Tier Architecture
2. **SECONDARY** — SentinelMesh Complete Elite Blueprint (supporting context only)

Where the two conflict, the 38-point architecture wins. Neither source's
functionality is silently removed. See `docs/ARCHITECTURE_DECISIONS.md` for the
recorded reconciliation of every ambiguity.

## Datasets

Benchmark/evaluation datasets (NSL-KDD, UNSW-NB15, CTU-13, EMBER, LANL unified
host/network) are staged **outside this repository** at `C:\Sentinel_Mesh` and
are referenced by absolute path in configuration. They are never committed.

## Repository layout

See [`docs/architecture/repository.md`](docs/architecture/repository.md).

## Local development

Not yet available. Phase 1 introduces `docker-compose` for local infrastructure
and the first runnable services. Required tooling and infrastructure are listed
in `docs/IMPLEMENTATION_STATE.md` under *External infrastructure requirements*.
