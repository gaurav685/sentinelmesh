# Repository structure

Derived from the 38-point architecture (not a template). Rule: a package may
import **downward** only — `frontend`/`services` → `packages` → (stdlib/third-party).
No service imports another service's internals; services communicate only through
published contracts (`packages/contracts-py`) at runtime via HTTP/Kafka.

| Path | Purpose | Owner boundary | Runtime | Deploy unit |
|---|---|---|---|---|
| `docs/` | Architecture, contracts, decisions, state | Architecture | none | n/a |
| `docs/architecture/` | Per-topic architecture documents | Architecture | none | n/a |
| `packages/contracts-py/` | Canonical event envelope, entity contracts, API request/response schemas, event payload schemas, `QueryPlan` — all Pydantic v2. Source of truth for JSON Schema. | Contracts | imported lib | published to all Python services |
| `packages/contracts-ts/` | TypeScript types generated from `contracts-py` JSON Schema. No hand-authored domain types. | Contracts | imported lib | frontend only |
| `packages/common-py/` | Cross-cutting: typed config loader + validation, structured logging, OTel tracing setup, request/correlation ID plumbing, error types, Postgres engine/session/tx helpers, Redis client, Kafka client wrappers, auth primitives (JWT verify, OIDC), audit-log writer, secret redaction. **No business logic.** | Platform | imported lib | all Python services |
| `services/ingestion-gateway/` | Req 1. Telemetry ingest HTTP API, sensor auth, envelope construction, size/rate limits, produce to `telemetry.raw`. | Ingestion | FastAPI | own (always) |
| `services/normalization-engine/` | Req 2. Consume `telemetry.raw`, validate + normalize + enrich (Geo-IP, hostname, identity stitch, TI tags), produce `events.canonical`. | Normalization | Kafka consumer + FastAPI (health) | monolith or own |
| `services/stream-processor/` | Req 20, 6, 10, 12, 5(feature agg). Flink jobs over `events.canonical`. | Stream processing | Flink (JVM/PyFlink) | own (always) |
| `services/graph-service/` | Reqs 3, 4, 19. Sole writer of Neo4j. Applies `graph.commands`; serves parameterized graph queries; runs GDS algorithms; manages operational vs knowledge graph. | Graph | FastAPI + Kafka consumer | monolith or own |
| `services/detection-engine/` | Reqs 5, 8. Orchestrates anomaly inference (calls `ml-inference`), computes composite threat score, emits `detections`, `attack_chains`. Statistical fallback when models `DEGRADED`. | Detection | FastAPI + Kafka consumer | monolith or own |
| `services/ml-inference/` | Reqs 5, 11, 15. Loads registered models from MLflow/S3, typed inference endpoints. | ML serving | FastAPI | own (always) |
| `services/ml-training/` | Reqs 5, 11, 15, 24, 34. Training + benchmark harness, dataset adapters, MLflow logging. Batch, not a server. | ML training | batch jobs | own (always) |
| `services/threat-intel-service/` | Req 9. IOC store-of-record, provider adapters, enrichment API, freshness/expiry/provenance. | Threat intel | FastAPI | monolith or own |
| `services/mitre-service/` | Req 7. ATT&CK technique catalog, technique mapping, confidence, heatmap data API, campaign alignment. | MITRE | FastAPI | monolith or own |
| `services/ai-analyst-service/` | Reqs 14, 29, 32, 33, 36. LLM provider adapters, evidence-grounded context builder, explanation contract, NL→`QueryPlan`, storytelling, root-cause. | AI analyst | FastAPI | own (always) |
| `services/agent-orchestrator/` | Reqs 30, 31. Multi-agent coordination, response engine, policy + approval + blast-radius + rollback + audit. | Response | FastAPI + Kafka consumer | own (always) |
| `services/deception-service/` | Req 16. Honeypot control plane, interaction capture. Network-isolated. | Deception | FastAPI + workers | own (always) |
| `services/simulation-service/` | Reqs 17, 26, 35. Attack simulation, demo scenario engine, security digital twin. Isolated; synthetic/deterministic data. | Simulation | FastAPI + workers | own (always) |
| `services/memory-service/` | Reqs 21, 37. Threat memory (Postgres + pgvector), campaign evolution, adversary fingerprint similarity. | Memory | FastAPI | monolith or own |
| `services/reporting-service/` | Req 22. Executive summaries, SOC reports, compliance reports (PDF to S3, pre-signed download). | Reporting | FastAPI + workers | monolith or own |
| `services/federation-service/` | Req 34. Federated-learning coordinator. **Deferred (ADR-023)** — contract stub only. | Federation | (deferred) | own (always) |
| `services/api-gateway/` | Req 24, 18, 25. The frontend's only backend (BFF). OIDC auth-code flow, session cookies, RBAC enforcement, request aggregation, rate limiting, audit, pagination/filter/sort validation. Owns no domain data — projects from other services + Postgres read models. | API edge | FastAPI | own (always) |
| `services/notification-service/` | Req 13. WebSocket gateway; consumes Redis fan-out stream; pushes live graph/alert updates to browsers; auth-scoped per tenant. | Realtime | FastAPI + WebSocket | own (always) |
| `frontend/web/` | Reqs 13, 18, 25, 26, 33. Next.js SOC dashboard. Talks only to `api-gateway` + `notification-service`. | Frontend | Next.js | own (always) |
| `ml/models/` | Model definitions (nn.Module classes, sklearn pipelines) shared by training + inference. | ML | imported lib | packaged with ml-* |
| `ml/features/` | Feature schemas + deterministic transforms (versioned). | ML | imported lib | packaged with ml-* + stream-processor |
| `ml/datasets/` | Dataset adapter code + `MANIFEST.md` per dataset (name, version, source, checksum, license). **No data.** | ML | imported lib | packaged with ml-training |
| `ml/notebooks/` | Exploration only. Never imported by runtime. | ML | none | n/a |
| `deploy/docker/` | Per-service Dockerfiles + `docker-compose.yml` (local infra + monolith). | Platform/SRE | n/a | n/a |
| `deploy/helm/` | Umbrella chart + per-service sub-charts. | SRE | n/a | production |
| `deploy/k8s/` | Raw manifests, NetworkPolicies, RBAC, namespaces. | SRE | n/a | production |
| `deploy/grafana/`, `deploy/prometheus/` | Dashboards, scrape configs, alert rules. | SRE | n/a | observability |
| `migrations/postgres/` | Alembic migrations. Single logical database, one migration history. | Data | applied by CI/ops | n/a |
| `migrations/neo4j/` | Versioned `.cypher` constraint/index migrations + runner. | Data | applied by CI/ops | n/a |
| `tests/contract/` | Cross-service contract tests (schemas, compatibility). | QA | pytest | CI |
| `tests/integration/` | docker-compose-backed integration tests. | QA | pytest | CI |
| `tests/e2e/` | Full-stack end-to-end (Playwright + API). | QA | pytest/Playwright | CI |
| `tests/security/` | AuthZ, tenant isolation, injection, prompt injection, mass-assignment. | Security | pytest | CI |
| `scripts/` | Dev/ops scripts (dataset staging, migration runners, codegen contracts-py → contracts-ts). | Platform | n/a | n/a |

**Circular-dependency guard.** `packages/common-py` must not import
`packages/contracts-py` domain modules that import back. `contracts-py` depends
only on Pydantic. Enforced by an import-linter config added in Phase 1.
