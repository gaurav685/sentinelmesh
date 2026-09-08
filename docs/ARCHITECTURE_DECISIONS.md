# SentinelMesh — Architecture Decision Record

Status of this document: **LIVING**. Every meaningful architecture decision is
recorded here with rationale, alternatives, and implications. Decisions are
append-only; a superseded decision is marked `SUPERSEDED BY ADR-NNN` and kept.

Authoritative source hierarchy:

1. **PRIMARY** — SentinelMesh Final 38-Point God-Tier Architecture
2. **SECONDARY** — SentinelMesh Complete Elite Blueprint

Where they conflict, the 38-point architecture wins. This document records how
each conflict/ambiguity was reconciled.

Verification note: technology **presence** in the local environment was checked
on 2026-09-08 (see ADR-001). No claim in this document asserts that any service,
container, cluster, model, or benchmark has been built, deployed, or measured.

---

## Decision index

| ADR | Title | Status |
|-----|-------|--------|
| ADR-001 | Local toolchain baseline (verified) | ACCEPTED |
| ADR-002 | Repository is a polyglot monorepo at `C:\Users\gmalh\sentinelmesh` | ACCEPTED |
| ADR-003 | Logical services vs. deployment profiles | ACCEPTED |
| ADR-004 | Backend runtime: Python 3.11 + FastAPI + Pydantic v2 | ACCEPTED |
| ADR-005 | Frontend: Next.js + React + TypeScript; Cytoscape.js + D3 | ACCEPTED |
| ADR-006 | Relational store: PostgreSQL 16 (+ pgvector) | ACCEPTED |
| ADR-007 | Graph store: Neo4j 5 (+ Graph Data Science) | ACCEPTED |
| ADR-008 | Durable event bus: Apache Kafka (Redpanda locally) | ACCEPTED |
| ADR-009 | Redis role: cache + ephemeral state + WebSocket fan-out only | ACCEPTED |
| ADR-010 | Stream processing: Apache Flink; PyFlink vs JVM unresolved | ACCEPTED (with open question) |
| ADR-011 | Operational attack graph vs. persistent knowledge graph vs. threat memory | ACCEPTED |
| ADR-012 | ML stack: PyTorch 2 + PyTorch Geometric + scikit-learn + PyOD; MLflow registry | ACCEPTED |
| ADR-013 | Model serving: in-process in `ml-inference` for MVP | ACCEPTED |
| ADR-014 | LLM access: provider-adapter pattern, no orchestration framework | ACCEPTED |
| ADR-015 | NL→graph query: constrained query-plan, never raw LLM Cypher execution | ACCEPTED |
| ADR-016 | AuthN/AuthZ: OIDC + server-side deny-by-default RBAC; tenant isolation model | ACCEPTED |
| ADR-017 | Multi-tenancy: shared-schema with mandatory `tenant_id` scoping; Neo4j tenant property + DB-per-tenant option | ACCEPTED (with open question) |
| ADR-018 | Canonical event envelope + Kafka topic taxonomy | ACCEPTED |
| ADR-019 | Object storage: S3-compatible (MinIO locally), cloud-agnostic core | ACCEPTED |
| ADR-020 | Observability: OpenTelemetry + Prometheus + Grafana + Loki | ACCEPTED |
| ADR-021 | Deployment: docker-compose (local) + Helm/Kubernetes (production) | ACCEPTED |
| ADR-022 | Autonomous response defaults to `suggest_only`; `auto` requires policy + environment gate | ACCEPTED |
| ADR-023 | Federated threat-intelligence mesh (req 34) deferred to a late phase | ACCEPTED |
| ADR-024 | Benchmark datasets stay outside the repo; evaluation is explicit and unclaimed | ACCEPTED |

---

## ADR-001 — Local toolchain baseline (verified)

**Context.** The Engineering Constitution forbids fabricated version
verification. The local Windows 11 environment was inspected on 2026-09-08.

**Verified present:**

| Tool | Version | Source |
|------|---------|--------|
| git | 2.55.0.windows.5 | `C:\Program Files\Git` |
| Python | 3.11.5 | `...\Programs\Python\Python311` |
| Node.js | 24.14.0 | `C:\Program Files\nodejs` |
| npm | 11.9.0 | bundled with Node |
| Java | 8 (Oracle, `java8path`) | `C:\Program Files (x86)\Common Files\Oracle\Java` |

**Verified absent:** `docker`, `docker-compose`, `uv`, `pnpm`, `helm`,
`kubectl`, a JDK ≥ 11.

**Decision.**

- Target **Python 3.11** (not 3.12) for all Python code, because 3.11 is what is
  installed. 3.12/3.13 remain compatible targets; CI will test the lowest
  supported (3.11).
- Use **npm workspaces** for the frontend, not pnpm (pnpm not installed; npm 11
  workspaces are sufficient). pnpm may be revisited in a later ADR.
- **Docker / Kubernetes / Flink runtime are NOT available locally.** Any Phase
  that needs them is `NOT VERIFIED — REQUIRES EXTERNAL INFRASTRUCTURE`. Phase 1
  will add a `docker-compose.yml`, but running it requires the user to install
  Docker Desktop (recorded as an external requirement).
- Java 8 is too old for Flink 1.18+ (needs Java 11+). Flink local execution is an
  external requirement; see ADR-010.

**Implications.** Phase 1 can proceed for pure-Python/TypeScript units (config,
domain models, contracts, migrations authored but not applied, unit tests).
Integration tests and anything container-based are blocked on Docker install.

---

## ADR-002 — Repository is a polyglot monorepo

**Context.** SentinelMesh spans 18 logical services, 3 shared packages, a
frontend, ML training/inference code, infra manifests, and migrations. The
Constitution requires clear ownership boundaries, no circular dependencies, and
separation of domain / application / infrastructure / API / frontend / ML /
deployment / schemas / tests / docs.

**Decision.** A single monorepo at `C:\Users\gmalh\sentinelmesh`, **outside**
OneDrive (the working directory `C:\Sentinel_Mesh` is OneDrive-synced and holds
~95 GB of datasets; a `.git` directory inside OneDrive risks index corruption
from background sync). Datasets remain at `C:\Sentinel_Mesh`, referenced by
absolute path via `SM_DATASET_ROOT`.

Layout is documented in `docs/architecture/repository.md`.

**Alternatives considered.**

- *Polyrepo (one repo per service).* Rejected: contract versioning and
  cross-cutting refactors become painful for a pre-Phase-1 system with one
  developer; the 38 requirements are tightly coupled.
- *Repo inside `C:\Sentinel_Mesh`.* Rejected: OneDrive sync + large sibling data
  + `.git` corruption risk.

**Implications.** Tooling must support per-package dependency isolation
(Python: per-service `pyproject.toml`; JS: npm workspaces). CI matrix keys off
changed paths.

---

## ADR-003 — Logical services vs. deployment profiles

**Context.** The architecture implies many services. The Constitution warns
against inventing microservices "to appear enterprise-grade" and against merging
services "to reduce effort". Both failure modes must be avoided.

**Decision.** Define **logical services** by ownership boundary (each owns a
clear slice of data and behavior, has its own inbound/outbound contracts). Ship
them under a **deployment profile**:

- `monolith` (default for local/dev/MVP) — the stateless request-path services
  (`api-gateway`, `ingestion-gateway`, `normalization-engine`,
  `graph-service`, `detection-engine`, `threat-intel-service`, `mitre-service`,
  `memory-service`, `reporting-service`, `notification-service`) run as **one
  process** importing each service package. Kafka, Postgres, Neo4j, Redis still
  run as real infrastructure.
- `distributed` (staging/production) — each logical service is its own
  deployable with independent scaling.

Stateful / specialized runtimes are **always separate**: `stream-processor`
(Flink), `ml-inference`, `ml-training`, `ai-analyst-service`,
`agent-orchestrator`, `deception-service`, `simulation-service`,
`federation-service`.

**Implications.** Every logical service is a Python package with **no direct
imports of another service's internals** — only its published contract package.
This keeps `monolith` honest (it is composition, not coupling) and makes the
`distributed` split mechanical.

---

## ADR-004 — Backend runtime: Python 3.11 + FastAPI + Pydantic v2

**Version.** Python 3.11.5 (local); FastAPI ≥ 0.115; Pydantic ≥ 2.9; Uvicorn
(dev) / Gunicorn+Uvicorn workers (prod); `httpx` for outbound; `asyncpg` +
SQLAlchemy 2.0 (async) for Postgres; `neo4j` official async driver;
`aiokafka` or `confluent-kafka` for Kafka (decided in Phase 1 after a spike);
`redis` (redis-py ≥ 5, async).

**Purpose.** Serves requirements 1, 2, 8, 9, 14, 18, 22, 24, 29, 32 (HTTP APIs,
ingestion endpoints, enrichment, scoring orchestration, LLM orchestration,
reporting) and hosts the request-path logical services.

**Why selected.**

- The ML ecosystem the architecture mandates (PyTorch, PyTorch Geometric,
  scikit-learn, PyOD) is Python-first. A single primary language reduces
  contract-drift and staffing cost.
- Pydantic v2 gives typed, validated request/response/event models cheaply —
  directly satisfies Constitution §7 (strong typing) and §8/§9 (API/event
  contracts) with one tool.
- FastAPI: native async, OpenAPI schema generation (feeds `contracts-ts`),
  dependency-injection for auth guards.

**Alternatives considered.**

- *Go* — best raw throughput for the ingestion hot path; rejected as the
  *primary* language because it splits the codebase from ML. **Kept as an
  option** for the ingestion gateway only if Phase-1 load testing shows Python
  cannot meet ingestion latency targets (open question, not a current decision).
- *Node/TypeScript backend* — rejected: would still need a Python sidecar for ML;
  double the contract surface.
- *Django* — rejected: heavier, sync-first, ORM-centric; poor fit for a
  streaming/event system.

**Operational implications.** GIL means CPU-bound work (feature extraction,
scoring) must run in worker processes or move to `ml-inference`. Async
discipline (Constitution §11) is mandatory — no blocking calls in the event
loop; DB/driver calls must be the async variants.

**Security implications.** Pydantic validation at every boundary (Constitution
§7). `ruff` bandit ruleset (`S`) enabled repo-wide. FastAPI security utilities
for auth dependencies; never trust client-supplied identity/tenant/role.

**Licensing.** Python (PSF), FastAPI (MIT), Pydantic (MIT), SQLAlchemy (MIT),
neo4j driver (Apache-2.0). All permissive.

**Local dev implications.** `python -m venv` per service, or `uv` once installed.
No compiler toolchain needed except for optional `confluent-kafka` (wheels
available on Windows).

**Production implications.** Gunicorn with Uvicorn workers behind the ingress;
`--max-requests` recycling; graceful shutdown wired to Kafka consumer close and
DB pool drain.

---

## ADR-005 — Frontend: Next.js + React + TypeScript; Cytoscape.js + D3

**Version.** Next.js 14 (App Router) / React 18 / TypeScript 5.x; Node 24 (local);
graph rendering **Cytoscape.js 3.x** (+ `cytoscape-cola`/`cytoscape-fcose`
layouts, canvas/WebGL renderer); **D3 7.x** for timelines, ATT&CK heatmaps, risk
heatmaps; TanStack Query for server state; a WebSocket client for live updates.

**Purpose.** Requirements 13, 18, 25, 26, 33 (attack-visualization dashboard,
threat-hunting panel, enterprise SOC UI, demo scenarios, attack storytelling).

**Why selected.**

- Cytoscape.js is purpose-built for large interactive graphs (styling, layouts,
  hit-testing, headless mode for tests), which is the core visual primitive.
- D3 covers the non-graph analytical visuals without a second graph library.
- Next.js: SSR/streaming for first paint, file-system routing, API-route BFF
  shim only if needed (the real BFF is `api-gateway`).

**Alternatives considered.** Sigma.js (WebGL-first, leaner API — kept as
fallback if Cytoscape perf is insufficient at 100k+ elements),
`react-force-graph` (less layout control), Vite SPA (rejected: lose SSR and
routing conventions), plain D3 for graphs (rejected: reinventing layout/interaction).

**Operational implications.** The frontend talks **only** to `api-gateway`
(REST + WebSocket). No direct database, Neo4j, or Kafka access from the browser —
a trust boundary (see `docs/architecture/security-model.md`).

**Security implications.** Strict CSP, no `dangerouslySetInnerHTML` for
LLM/analyst text without sanitization, auth via httpOnly secure cookie session
minted by `api-gateway` after OIDC. Client never receives raw provider tokens.

**Licensing.** Next.js (MIT), React (MIT), Cytoscape.js (MIT), D3 (ISC). All
permissive.

**Local dev.** `npm install` at repo root (workspace), `npm --workspace
frontend/web run dev`.

**Production.** Static+SSR build served by Node runtime container or edge;
API base URL and OIDC config injected at runtime, not baked.

---

## ADR-006 — Relational store: PostgreSQL 16 (+ pgvector)

**Version.** PostgreSQL 16; extensions `pgvector` (≥ 0.7), `pg_partman` for
time-range partitioning of high-volume derived tables; migrations via **Alembic**.

**Purpose.** System of record for: tenants, users, roles, permissions, assets,
identities, security alerts, detections, investigations, incidents, agent tasks,
response actions, hunt queries, analyst messages, MITRE technique catalog,
threat-memory metadata + embeddings, benchmark experiment metadata,
threat-intel IOC cache-of-record. Requirements 1, 7, 9, 18, 21, 22, 24, 29, 30,
31, 37.

**Why selected.** Named in the Blueprint; strong constraints/transactions
(Constitution §10); `pgvector` covers campaign-similarity / adversary-fingerprint
similarity search (reqs 34, 37) without adding a dedicated vector DB.

**Alternatives considered.**

- *TimescaleDB* for time-series — **rejected for the core**: adds operational
  weight; infra metrics belong in Prometheus; partitioned vanilla Postgres
  handles detection/alert history. May be reconsidered if
  temporal-analytics queries (req 12) become a bottleneck (open question).
- *Dedicated vector DB (Qdrant/Weaviate)* — rejected initially: `pgvector`
  suffices at expected scale; revisit if recall/latency require it.

**Operational implications.** Connection pooling per service (bounded), statement
timeout enforced (`SM_PG_STATEMENT_TIMEOUT_MS`), no unbounded queries, explicit
pagination on every list endpoint (Constitution §8, §10).

**Security implications.** Parameterized queries only (SQLAlchemy core/ORM, never
string interpolation). Row-level `tenant_id` scoping enforced in a repository
layer; optionally Postgres RLS policies as defense-in-depth (Phase 1 decision).
DB credentials are `[secret]`; internal errors never surfaced to clients.

**Licensing.** PostgreSQL License (permissive), pgvector (PostgreSQL License),
pg_partman (PostgreSQL License).

**Local dev.** Postgres 16 container in `docker-compose` (Phase 1).

**Production.** Managed Postgres (e.g. RDS) as reference; automated backups,
PITR, read replicas for the temporal/reporting read path.

---

## ADR-007 — Graph store: Neo4j 5 (+ Graph Data Science)

**Version.** Neo4j 5.x; **Community Edition** for local/dev; **Graph Data
Science (GDS)** library for pathfinding, centrality, and community detection
(reqs 5, 10, 11); official async Python driver; Cypher.

**Purpose.** The operational attack graph (reqs 3, 4), the persistent knowledge
graph (req 19), and graph-query surface for hunting (req 18), NL hunting (req 32),
lateral-movement analysis (req 10), attack-chain traversal (req 6), and
memory-augmented reasoning (req 37).

**Why selected.** Explicitly named in the 38-point architecture. Largest graph
ecosystem, mature Cypher, GDS covers the graph-algorithm requirements without a
separate compute engine.

**Alternatives considered.**

- *Memgraph* — faster, in-memory, MAGE algorithms, but BSL license and smaller
  ecosystem. Rejected because the architecture names Neo4j; noted as a drop-in
  candidate if write-throughput becomes limiting.
- *Amazon Neptune* — AWS lock-in, no GDS equivalent. Rejected for cloud-agnostic
  core (ADR-019).
- *Postgres + AGE / recursive CTEs* — rejected: loses the graph-algorithm
  library and the interactive-traversal performance the SOC UI needs.

**Licensing — IMPORTANT.** Neo4j Community is **GPLv3**; Enterprise features
(clustering, multi-database at scale, fine-grained RBAC, hot backup) are
**commercial**. GDS has its own license (free for development/self-hosted single
instance; production/enterprise terms differ). This is an **open commercial
question** for production and is tracked as an unresolved decision in
`docs/IMPLEMENTATION_STATE.md`. It does not block development.

**Operational implications.** Query timeout enforced
(`SM_NEO4J_QUERY_TIMEOUT_MS`); bounded traversal depth on all
externally-triggered queries; graph migrations (constraints, indexes) are
versioned `.cypher` files with a runner in `migrations/neo4j`.

**Security implications.** All Cypher is **parameterized** — no string
interpolation, no LLM-authored Cypher executed directly (ADR-015). A read-only
Neo4j role backs the hunting/NL/query path; writes go only through
`graph-service`.

**Local dev.** Neo4j 5 Community container in `docker-compose` (Phase 1).

**Production.** Managed or self-hosted; licensing decision required before a
production launch.

---

## ADR-008 — Durable event bus: Apache Kafka (Redpanda locally)

**Version.** Apache Kafka 3.7+ wire protocol. Local/dev: **Redpanda** (single
binary, Kafka-API-compatible, lower memory, no ZooKeeper/KRaft ceremony).
Production: Kafka (KRaft mode) or a managed equivalent (MSK / Redpanda Cloud /
Confluent).

**Purpose.** The single **durable, replayable** event log for the canonical
event stream and all inter-service asynchronous events. Requirements 1, 2, 4, 6,
12, 20, 30. Enables historical replay (reqs 4, 12) and temporal reconstruction.

**Why selected.** Named in the architecture. Durable ordered partitions,
consumer groups, retention + compaction, DLQ pattern, mature clients. Redpanda
locally removes the operational burden while keeping the exact API.

**Alternatives considered.**

- *Redis Streams as the bus* — rejected: weaker durability/replay story, memory
  bound; Redis has a different role here (ADR-009).
- *NATS JetStream* — lighter, but smaller ecosystem for the stream-processing
  integration (Flink connectors, Debezium, schema registry). Rejected.
- *Cloud-native (Kinesis / PubSub)* — rejected for cloud-agnostic core.

**Operational implications.** Topic taxonomy, partitioning by `tenant_id`
(ordering guarantee is *per partition* = per tenant per key), consumer-group
naming, retention, and DLQ topics are defined in ADR-018 and
`docs/architecture/event-model.md`. **Exactly-once is NOT claimed**; the design
is at-least-once + idempotent consumers + dedup keys.

**Security implications.** Production: SASL_SSL + ACLs per service principal.
Local: PLAINTEXT on a private network. Event payloads carrying sensitive data are
subject to field-level redaction rules before they leave a trust boundary.

**Licensing.** Apache Kafka (Apache-2.0); Redpanda core (BSL 1.1, converts to
Apache-2.0 after 4 years) — acceptable for local dev; production choice is
open.

**Local dev.** Redpanda container in `docker-compose` (Phase 1) — requires
Docker (external requirement).

---

## ADR-009 — Redis role: cache + ephemeral state + WebSocket fan-out only

**Context.** The architecture lists "Redis Streams / Kafka" together (req 20).
The Constitution explicitly warns not to assume Kafka, Redis, and Flink perform
the same role.

**Decision.** Redis is **not** the durable event bus. Its responsibilities:

| Namespace (`sm:` prefix) | Purpose | TTL | Owner |
|---|---|---|---|
| `sm:cache:geoip:<ip>` | Geo-IP lookup cache | 24h | normalization-engine |
| `sm:cache:ti:<indicator>` | Threat-intel reputation cache | `SM_TI_CACHE_TTL_S` | threat-intel-service |
| `sm:session:<sid>` | User session state | session length | api-gateway |
| `sm:ratelimit:<principal>:<window>` | Rate-limit counters | window | api-gateway / ingestion-gateway |
| `sm:dedup:<consumer>:<event_id>` | Consumer-side idempotency set | short (minutes) | each Kafka consumer |
| `sm:fanout:<tenant>` (Redis Stream) | Live graph/alert updates → WebSocket gateway | capped stream | notification-service |
| `sm:lock:<resource>` | Short-lived advisory locks | seconds | various |

**Redis Streams are used only** for the `notification-service` → browser fan-out
buffer, never for cross-service business events.

**Implications.** Loss of Redis degrades but does not lose data: caches repopulate,
sessions require re-auth, rate limiting fails **closed** (reject) for ingestion
and **open with alarm** for read APIs (Phase 1 confirms), WebSocket updates pause
(clients fall back to polling). See `docs/architecture/failure-model.md`.

---

## ADR-010 — Stream processing: Apache Flink (open question: PyFlink vs JVM)

**Version.** Apache Flink 1.18+ (needs JDK 11+, absent locally — ADR-001).

**Purpose.** Stateful stream processing over the canonical Kafka stream:

- windowed feature aggregation feeding anomaly detection (req 5)
- attack-stage correlation for attack-chain detection (req 6)
- lateral-movement sessionization (req 10)
- temporal event stitching / cross-session identity correlation (reqs 2, 12)
- emission of graph-update commands (reqs 3, 4)

Flink **consumes** canonical events from Kafka and **produces** derived events +
graph-update commands **back to Kafka**. It does not write to Neo4j/Postgres
directly — `graph-service` and `detection-engine` own those writes.

**Why selected.** Named in the 38-point architecture; true event-time semantics,
large keyed state with checkpointing, exactly-once *within a job* (source→sink
still at-least-once across the system).

**Open question (unresolved decision U-001).** **PyFlink vs. JVM (Java/Scala)
jobs.** PyFlink keeps language cohesion but lags on features and has UDF
serialization overhead; JVM jobs are first-class but add a second language +
build toolchain. Deferred to a Phase-2 spike with a representative job.

**Fallback (unresolved decision U-002).** If Flink's operational cost is
unjustified at MVP scale, **Bytewax** (Python, Rust core) or **Kafka Streams**
(JVM, no separate cluster) are candidates. The stream-processing *contracts*
(input topics, output topics, semantics) are defined engine-independently in
`docs/architecture/event-model.md` so the engine can change without a contract
break.

**Licensing.** Apache-2.0.

**Local / production.** Flink requires JDK 11+ and (for anything realistic) a
container or cluster — `NOT VERIFIED — REQUIRES EXTERNAL INFRASTRUCTURE`.

---

## ADR-011 — Operational attack graph vs. persistent knowledge graph vs. threat memory

**Context.** Requirements 3/4 (dynamic attack graph), 19 (knowledge graph,
persistent attack memory), 21 (threat memory system), and 37
(memory-augmented reasoning) risk duplicating state. The Constitution forbids
duplicating state without a documented reason.

**Decision — three distinct stores, one graph database:**

1. **Operational attack graph** — Neo4j, "hot" subgraph: recent entities and
   relationships (rolling window, e.g. 30–90 days, configurable), continuously
   updated from the stream. Optimized for interactive traversal and live
   visualization. Owner: `graph-service`.
2. **Persistent knowledge graph** — Neo4j (same instance, distinct label
   namespace / or a second database when on Enterprise): durable, curated
   entities, confirmed attack chains, campaigns, threat actors, ATT&CK technique
   nodes, historical attacker profiles. Written only on promotion events
   (investigation closed, chain confirmed). Owner: `graph-service` +
   `memory-service`.
3. **Threat memory** — PostgreSQL (+ pgvector): behavioral pattern records,
   campaign-evolution timelines, adversary fingerprints (feature vectors +
   embeddings), cross-incident statistics. This is *analytical/vector* state,
   not graph state. Owner: `memory-service`.

**Memory-augmented reasoning (req 37)** is a *consumer* of all three plus the
predictive engine — it introduces **no new store**. It is a capability of
`ai-analyst-service` / `agent-orchestrator` backed by `memory-service` retrieval.

**Rationale for the split.** Different access patterns (interactive traversal vs.
curated history vs. similarity search), different retention, different
write triggers. The knowledge graph and operational graph share the DB engine to
allow cross-queries (e.g. "has this live IP appeared in a past campaign?")
without cross-store joins.

---

## ADR-012 — ML stack: PyTorch 2 + PyTorch Geometric + scikit-learn + PyOD; MLflow registry

**Version.** PyTorch 2.x, PyTorch Geometric 2.x (reqs 5, 11, 15);
scikit-learn 1.5+ (Isolation Forest — req 5); PyOD 2.x (autoencoder and anomaly
model zoo — req 5); MLflow 2.x (experiment tracking — req 24, model registry,
artifact store on S3-compatible object storage — ADR-019).

**Purpose.** Requirements 5 (anomaly detection), 11 (GNN layer — GraphSAGE/GAT),
15 (predictive threat engine), 24 (benchmark & evaluation), 34 (federated
learning — deferred, ADR-023).

**Why selected.** Named in the Blueprint; PyG is the standard for GraphSAGE/GAT;
scikit-learn's IsolationForest is the reference implementation; MLflow gives
experiment tracking + versioned model registry + artifact lineage, which is
exactly what Constitution §13 and req 24 require.

**Alternatives considered.** DGL instead of PyG (comparable; PyG chosen for
larger community + simpler API), Weights & Biases instead of MLflow (SaaS, less
self-hostable — rejected for cloud-agnostic core), a hand-rolled registry
(rejected — reinvents lineage/versioning).

**Reproducibility (Constitution §13).** Every training run records: dataset
identifier + hash, feature-schema version, preprocessing version, hyperparameters,
random seeds, library versions, git commit. Models are immutable artifacts keyed
by version.

**Performance claims.** **NONE.** No accuracy / precision / recall / F1 / ROC-AUC
value will appear anywhere until an actual training + evaluation run on a real
dataset has been executed. Until then every such field reads
`NOT VERIFIED — REQUIRES REAL DATA / TRAINING ENVIRONMENT`.

**Licensing.** PyTorch (BSD-3), PyG (MIT), scikit-learn (BSD-3), PyOD (BSD-2),
MLflow (Apache-2.0).

**Local implications.** CPU-only locally (no GPU verified). GNN training at
dataset scale needs a GPU — external requirement.

---

## ADR-013 — Model serving: in-process in `ml-inference` for MVP

**Decision.** Trained models are loaded **in-process** by a dedicated
`ml-inference` FastAPI service (one process, models loaded at startup from the
MLflow registry / S3, hot-reload on a new registered version via a control
message). It exposes typed inference endpoints consumed by `detection-engine`.

**Alternatives considered.** TorchServe / NVIDIA Triton (rejected for MVP —
extra infrastructure; revisit when throughput or multi-model GPU packing
demands it), in-process inside `detection-engine` (rejected — couples model
runtime memory/lifecycle to the request path and blocks the `distributed`
split).

**Failure behavior (Constitution §13, §17).** If a model is unavailable or an
inference call times out, `detection-engine` records the event as
`scoring_status = DEGRADED`, emits a metric, and falls back to
statistical/rule-based scoring — it does **not** silently drop detections or
fabricate a score.

---

## ADR-014 — LLM access: provider-adapter pattern, no orchestration framework

**Decision.** All LLM use (reqs 14, 29, 30, 31, 32, 33, 36, 37) goes through a
thin **provider-adapter** interface (Constitution §12):

```
application  →  LlmClient (interface)  →  {AnthropicAdapter | OpenAiAdapter | LocalAdapter}  →  external API
```

Adapters handle auth, timeout, retry-with-backoff, rate-limit handling, response
schema validation, token accounting, and error normalization. Default provider
and model come from config (`SM_LLM_DEFAULT_PROVIDER`, `SM_LLM_DEFAULT_MODEL`);
**model IDs are pinned at implementation time** — current Anthropic model
identifiers are documented in the `claude-api` reference and must be looked up
then, not guessed.

**No orchestration framework** (LangChain / LlamaIndex / etc.). Rationale:
abstraction churn, hidden prompt construction, hard-to-audit tool routing — all
at odds with Constitution §13 (grounding, auditability) and §5 (security). A
small typed orchestration layer in `ai-analyst-service` builds context
explicitly, calls native provider tool-use APIs, and logs every prompt +
response + tool call for audit.

**Grounding & injection defense.** Context passed to the LLM is assembled from
system evidence only, with provenance tags. Retrieved content (alerts, graph
snippets, threat-intel) is treated as **data, not instructions** — wrapped and
labeled. Tool calls are allow-listed per task type and per caller role.
Prompt-injection test cases are part of the security test suite.

**No fabricated LLM responses** anywhere, including tests — LLM calls in tests
use recorded fixtures at an explicit boundary, never presented as live output.

---

## ADR-015 — NL→graph query: constrained query-plan, never raw LLM Cypher

**Context.** Requirement 32 ("AI-to-Cypher translation", "conversational SOC
interface"). The Constitution: "Never allow unrestricted LLM-generated database
execution."

**Decision.** The pipeline is:

```
natural language
  → LLM produces a typed QueryPlan (intent enum + typed parameters + entity refs)
  → QueryPlan is schema-validated and authorization-checked (tenant, role, allowed intents, depth/row caps)
  → a deterministic QueryBuilder emits parameterized Cypher from the QueryPlan
  → executed against a READ-ONLY Neo4j role, with timeout + row limit
  → results + a grounded natural-language explanation returned
```

The LLM **never emits Cypher that is executed**. The `QueryPlan` schema is a
closed contract (documented in `docs/CONTRACTS.md`). Unsupported requests return
"cannot express this query", not a best-effort raw query.

---

## ADR-016 — AuthN/AuthZ: OIDC + server-side deny-by-default RBAC

**Decision.**

- **Authentication.** OIDC/OAuth2 (req 38 SSO). Local/dev: Keycloak realm
  `sentinelmesh`. Production: enterprise IdP via standard OIDC. `api-gateway`
  performs the auth-code flow and mints an **httpOnly, Secure, SameSite** session
  cookie; the browser never holds provider or internal tokens.
- **Service-to-service.** Short-lived internal JWTs signed with
  `SM_INTERNAL_JWT_SIGNING_KEY` (rotated), audience-scoped per service.
  Production adds mTLS at the mesh/ingress layer.
- **Authorization.** **Deny-by-default.** Every endpoint declares required
  `(permission, resource-scope)`. A central policy module resolves
  `identity → tenant → roles → permissions` server-side. Client-supplied roles,
  permissions, tenant IDs, and ownership claims are **never** trusted
  (Constitution §5, §6).
- **Audit.** Auth decisions, privileged actions, hunt queries, LLM tool calls,
  and response actions are written to an append-only audit log (Postgres,
  hash-chained per tenant — Phase 1 confirms the mechanism).

**Password handling.** If any local credential store exists at all, hashing is
Argon2id. Primary path is federated (no local passwords).

---

## ADR-017 — Multi-tenancy: shared-schema with mandatory `tenant_id` scoping

**Decision.**

- **PostgreSQL.** Shared schema; every tenant-scoped table has a non-null
  `tenant_id` FK to `tenant`. All access goes through a repository layer that
  **injects the tenant predicate** from the authenticated context — callers
  cannot pass their own `tenant_id`. Postgres RLS policies are added as
  defense-in-depth (Phase 1 decides mandatory vs. optional).
- **Kafka.** Events carry `tenant_id` in the envelope; topics are partitioned by
  `tenant_id`. Consumers filter defensively.
- **Neo4j.** Every node carries a `tenant_id` property; every query is scoped by
  it via the query layer. **Open question (unresolved decision U-003):** at what
  tenant count / isolation requirement do we move to database-per-tenant (Neo4j
  Enterprise)? Documented, not blocking.
- **Redis.** Keys are tenant-prefixed where the value is tenant-scoped.
- **Object store.** Per-tenant key prefixes; bucket policies in production.

**Testing.** Cross-tenant access attempts are a mandatory part of the security
test suite (Constitution §6, §16) for every API and every query path.

---

## ADR-018 — Canonical event envelope + Kafka topic taxonomy

**Decision (envelope).** The canonical event envelope fields:

| Field | Type | Notes |
|---|---|---|
| `event_id` | UUIDv7 | globally unique, time-ordered; idempotency key |
| `event_type` | string enum | e.g. `telemetry.network_flow.v1` |
| `event_version` | int | schema version of `payload` |
| `occurred_at` | RFC3339 UTC | event time (from source) |
| `ingested_at` | RFC3339 UTC | set by ingestion-gateway |
| `producer` | string | service name + version |
| `tenant_id` | UUID | required on every event |
| `source` | object | `{ type, sensor_id, site }` |
| `correlation_id` | UUID | investigation / request correlation |
| `trace_id` | string | W3C trace-context, for OTel |
| `partition_key` | string | derived (tenant + entity) — controls ordering |
| `payload` | object | type-specific, schema-validated |
| `metadata` | object | non-authoritative annotations (enrichment provenance, tags) |

**Serialization.** JSON for MVP with **JSON Schema** validation at every boundary
(schemas live in `packages/contracts-py`, generated to `contracts-ts`). A
schema-registry + Avro/Protobuf migration is an explicit later option
(unresolved decision U-004) once event volume justifies it.

**Semantics.** At-least-once delivery; consumer idempotency via `event_id`
+ a dedup set (ADR-009); ordering guaranteed only within a partition
(= per tenant per `partition_key`); out-of-order handling via `occurred_at`
watermarks in Flink; poison messages → per-topic `<topic>.dlq`; retention and
replay windows per topic class.

**Topic taxonomy (initial).**

| Topic | Produced by | Consumed by | Key | Retention |
|---|---|---|---|---|
| `telemetry.raw` | ingestion-gateway | normalization-engine | tenant+sensor | 7d |
| `events.canonical` | normalization-engine | stream-processor, graph-service, detection-engine, memory-service | tenant+entity | 30d |
| `graph.commands` | stream-processor, detection-engine | graph-service | tenant+entity | 7d |
| `detections` | detection-engine | api-gateway (projection), ai-analyst-service, agent-orchestrator, reporting-service | tenant | 90d |
| `attack_chains` | stream-processor/detection-engine | graph-service, ai-analyst-service, reporting-service | tenant | 180d |
| `agent.tasks` | agent-orchestrator, ai-analyst-service | agent-orchestrator workers | tenant | 30d |
| `response.actions` | agent-orchestrator | integrations, audit | tenant | 365d |
| `*.dlq` | any consumer | ops tooling | original key | 30d |

Full detail (partition counts, consumer groups, compaction) is in
`docs/architecture/event-model.md` (Phase 0 Unit 2).

**Exactly-once is NOT claimed** anywhere in the system.

---

## ADR-019 — Object storage: S3-compatible, cloud-agnostic core

**Decision.** All large-artifact storage (ML model artifacts, Flink checkpoints,
generated PDF reports, simulation bundles, dataset-derived feature caches) uses
an **S3-compatible API**. Local/dev: **MinIO**. Production: AWS S3 (reference) or
any S3-compatible service. No proprietary cloud service sits on a core runtime
path; AWS is a *target*, not a *dependency*.

**Security.** Per-tenant key prefixes; server-side encryption; time-limited
pre-signed URLs for report download (never public buckets); no user-controlled
keys/paths (SSRF / path-traversal guard).

---

## ADR-020 — Observability: OpenTelemetry + Prometheus + Grafana + Loki

**Decision.** Requirements 23, 38.

- **Traces:** OpenTelemetry SDK in every service; OTLP → collector → (Tempo or
  Jaeger). `trace_id` flows through the event envelope so async hops stay
  correlated.
- **Metrics:** Prometheus scrape per service (`SM_PROMETHEUS_METRICS_PORT`).
  Standard set: request latency/error counters, Kafka consumer lag, DB pool
  saturation, Neo4j query latency, model inference latency + `DEGRADED` counter,
  queue depths, graph growth rate, detection latency, false-positive feedback
  counter (req 23).
- **Logs:** structured JSON (`SM_LOG_FORMAT=json`), shipped to Loki; secret
  redaction filter mandatory (Constitution §5, §18).
- **Health:** every service exposes `/healthz` (liveness), `/readyz`
  (readiness — checks its own required dependencies), `/health/deps` (detailed
  dependency status for ops).

**No fabricated measurements.** Dashboards ship empty; every latency/throughput
number is either live from Prometheus or absent.

---

## ADR-021 — Deployment: docker-compose (local) + Helm/Kubernetes (production)

**Decision.** Requirement 38.

- **Local:** `docker-compose.yml` brings up Postgres, Neo4j, Redpanda, Redis,
  MinIO, Keycloak, Prometheus, Grafana, MLflow, plus the app in `monolith`
  profile. **Requires Docker Desktop — external requirement, not present
  locally (ADR-001).**
- **Production:** Helm umbrella chart, one sub-chart per logical service;
  namespaces (`sentinelmesh-system`, `-data`, `-app`, `-ml`, `-observability`);
  NetworkPolicies default-deny; Kubernetes RBAC + ServiceAccounts per service;
  secrets via External Secrets Operator (Vault/cloud KMS); HPA on the stateless
  request path; PodDisruptionBudgets; readiness/liveness/startup probes;
  rolling updates with surge=1, unavailable=0; PersistentVolumes for stateful
  sets; Velero (or managed) backup.

**No claim** of a successful cluster rollout will be made without an actual
verified deployment.

---

## ADR-022 — Autonomous response defaults to `suggest_only`

**Decision.** Requirements 29, 30, 31.

- `SM_RESPONSE_MODE` ∈ `{ suggest_only, approve_required, auto }`, default
  **`suggest_only`**.
- `auto` is **rejected at config validation** unless `SM_ENV=production` **and** a
  signed response-policy document is present **and** the specific action type is
  on the policy allow-list.
- Every response action has: an authorization check, a policy check, a computed
  blast-radius, a required approver (for `approve_required`), a rollback plan,
  and an audit record. Actions without a rollback plan cannot be `auto`.
- **No real endpoint isolation / firewall change is claimed** without an actual
  verified integration. Integrations are provider adapters (Constitution §12)
  behind a feature flag, default off.

---

## ADR-023 — Federated threat-intelligence mesh (req 34) deferred

**Decision.** Requirement 34 (federated learning, distributed anomaly learning,
collective defense) is architecturally acknowledged and traced, but its
**implementation is deferred to a late phase** (after core detection + ML +
multi-tenant isolation are verified). Rationale: it depends on a stable model
architecture (ADR-012), a hardened tenant-isolation boundary (ADR-017), and a
poisoning-defense design that cannot be meaningfully specified before the base
anomaly/GNN models exist. `federation-service` exists in the skeleton as a
placeholder with a documented contract stub only.

No federated-learning performance will be claimed without actual evaluation.

---

## ADR-024 — Benchmark datasets stay outside the repo; evaluation is explicit and unclaimed

**Decision.** Requirement 24. Datasets (NSL-KDD, UNSW-NB15, CTU-13, EMBER, LANL
unified host/network; CICIDS2017 to be added) live at `C:\Sentinel_Mesh`
(`SM_DATASET_ROOT`), never committed (`.gitignore`). `ml/datasets/` contains only
**dataset adapter code** (loaders, schema mappers, splitters) and dataset
**manifests** (name, version, source URL, checksum, license).

The `ml-training` service owns the benchmark harness: dataset ingest →
preprocessing (versioned) → experiment config → training → evaluation → metrics
logged to MLflow → report. **No metric (ROC-AUC, F1, precision, recall,
detection rate, FPR, latency) is written to any document or dashboard until the
corresponding experiment has actually been run.** Until then:
`NOT VERIFIED — REQUIRES REAL DATA / TRAINING ENVIRONMENT`.

Dataset licenses (research-use restrictions on several) are recorded per-dataset
in `ml/datasets/<name>/MANIFEST.md` and must be reviewed before any
redistribution or commercial claim.

---

## Open / unresolved decisions (tracked)

| ID | Question | Blocking? | Target phase |
|----|----------|-----------|--------------|
| U-001 | PyFlink vs JVM Flink jobs | No | Phase 2 spike |
| U-002 | Flink vs Bytewax vs Kafka Streams if Flink ops cost too high | No | Phase 2 |
| U-003 | Neo4j database-per-tenant threshold (Enterprise licensing) | No (dev) / Yes (prod) | before production |
| U-004 | JSON+JSON-Schema vs schema-registry + Avro/Protobuf for events | No | Phase 3 (volume-driven) |
| U-005 | Postgres RLS mandatory vs. repository-layer-only tenant scoping | No | Phase 1 |
| U-006 | Ingestion hot path stays Python vs. moves to Go | No | Phase 1 load test |
| U-007 | Cytoscape.js vs Sigma.js at 100k+ graph elements | No | Phase 4 (UI) |
| U-008 | Neo4j GDS production licensing | Yes (prod) | before production |
| U-009 | In-process model serving vs TorchServe/Triton | No | when throughput demands |
| U-010 | Dedicated vector DB vs pgvector for memory/campaign similarity | No | scale-driven |

These are also mirrored in `docs/IMPLEMENTATION_STATE.md`.
