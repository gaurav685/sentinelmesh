# Service catalog

Each **logical service** below has one ownership boundary. Deployment grouping is
per ADR-003 (`monolith` for local/MVP, `distributed` for production). "Owns
(data)" means: the only writer of that store/dataset.

Dependency rule: no cycles. The dependency graph is a DAG rooted at
`ingestion-gateway` (async) and `api-gateway` (sync).

---

## ingestion-gateway  (req 1)

- **Purpose:** accept telemetry from sensors; authenticate sensor; build canonical envelope; enforce size/rate limits; produce to `telemetry.raw`.
- **Owns (data):** nothing durable (stateless). Sensor credential *verification* only; sensor registry owned by `api-gateway`/Postgres.
- **Consumes:** HTTP from sensors; sensor registry (read, cached) from Postgres.
- **Produces:** Kafka `telemetry.raw`.
- **DB:** Postgres (read-only: sensor registry); Redis (rate-limit counters, dedup).
- **External deps:** none.
- **Sync deps:** Postgres.
- **Async deps:** Kafka (produce).
- **AuthN:** per-sensor credential (API key → mTLS in prod).
- **AuthZ:** sensor may write only its bound `tenant_id`; `event.tenant_id` is overwritten with the bound value, never trusted from body.
- **Failure:** Kafka down → 503 + retry-after, sensor buffers; Postgres down → serve from cached registry, refuse unknown sensors; oversize → 413; rate exceeded → 429 (fail-closed).
- **Scaling:** horizontal, stateless, CPU-bound on validation.
- **Observability:** ingest rate, reject reasons counter, produce latency, envelope-validation failures.

## normalization-engine  (req 2)

- **Purpose:** raw → canonical. Schema-standardize, Geo-IP, hostname resolution, user-device linking, cross-session identity stitching, threat-intel tagging.
- **Owns (data):** identity-stitch state (Postgres table `identity_link`), enrichment provenance in event `metadata`.
- **Consumes:** Kafka `telemetry.raw`; `threat-intel-service` (enrichment API); Geo-IP file; Postgres (identity links, asset registry read).
- **Produces:** Kafka `events.canonical`; DLQ `telemetry.raw.dlq`.
- **DB:** Postgres (identity/asset), Redis (geoip + TI cache).
- **External deps:** none directly (TI is via `threat-intel-service`).
- **Sync deps:** `threat-intel-service`, Postgres, Redis.
- **Async deps:** Kafka (consume + produce).
- **AuthN/AuthZ:** internal JWT; operates across tenants but every output event keeps its source `tenant_id`.
- **Failure:** TI unavailable → emit event with `metadata.ti_enrichment = SKIPPED`, never block; Geo-IP missing → `geo = null`; unparseable raw → DLQ with reason; identity store down → emit without stitch, flag `identity_status = PARTIAL`.
- **Scaling:** horizontal by partition; consumer group.
- **Observability:** normalization latency, enrichment hit/miss/skip, DLQ rate, per-type throughput.

## stream-processor  (reqs 20, 6, 10, 12, 5-features, 3/4-commands)

- **Purpose:** stateful event-time processing. Jobs: `feature-aggregator`, `attack-chain-correlator`, `lateral-movement`, `temporal-stitcher`, `graph-update-emitter`.
- **Owns (data):** Flink keyed state + checkpoints (S3). No system-of-record data.
- **Consumes:** Kafka `events.canonical`.
- **Produces:** Kafka `graph.commands`, `attack_chains`, feature/derived-event topics.
- **DB:** none (state is Flink-internal, checkpointed to S3).
- **External deps:** S3 (checkpoints).
- **Sync deps:** none.
- **Async deps:** Kafka (consume + produce), S3.
- **AuthN/AuthZ:** internal principal; cross-tenant consumer, per-key tenant isolation in state (key includes `tenant_id`).
- **Failure:** job crash → restart from last checkpoint (at-least-once downstream); watermark skew → bounded lateness + side-output for late events; backpressure → Kafka lag grows (alarmed), no data loss.
- **Scaling:** Flink parallelism / task slots.
- **Observability:** per-job lag, checkpoint duration/size/failures, watermark lag, late-event count.

## graph-service  (reqs 3, 4, 19)

- **Purpose:** the only Neo4j writer. Apply `graph.commands` to the operational graph; promote confirmed entities/chains to the knowledge graph; serve parameterized, depth-bounded, tenant-scoped graph queries; run GDS algorithms (pathfinding, centrality, community).
- **Owns (data):** all of Neo4j.
- **Consumes:** Kafka `graph.commands`, `attack_chains`; sync graph-query requests from `api-gateway`, `ai-analyst-service`, `detection-engine`.
- **Produces:** Redis fan-out (graph deltas), Kafka `graph.events` (node/edge lifecycle).
- **DB:** Neo4j (read+write), Redis (fan-out publish).
- **Sync deps:** Neo4j.
- **Async deps:** Kafka (consume + produce), Redis.
- **AuthN/AuthZ:** internal JWT; every query requires `tenant_id` from caller context; separate read-only Neo4j role for query path vs write role for command path.
- **Failure:** Neo4j down → command consumer pauses (lag, no loss), query API returns 503; malformed command → `graph.commands.dlq`; idempotent apply keyed by `command_id`.
- **Scaling:** query path horizontal (read replicas / read role); write path single-writer per partition to preserve ordering.
- **Observability:** command apply latency, query latency by pattern, graph size/growth, GDS job duration, DLQ rate.

## detection-engine  (reqs 5, 8)

- **Purpose:** orchestrate anomaly inference; compute deterministic composite threat score; emit detections and attack-chain candidates; MITRE mapping trigger.
- **Owns (data):** Postgres `detection`, `anomaly`, `threat_score` tables (system of record for detections).
- **Consumes:** Kafka `events.canonical`, derived feature topics, `attack_chains`; `ml-inference` (sync); `mitre-service` (sync); `threat-intel-service` (sync); `graph-service` (sync context).
- **Produces:** Kafka `detections`; Postgres writes; Redis fan-out (new detection).
- **DB:** Postgres (read+write), Redis.
- **Sync deps:** `ml-inference`, `mitre-service`, `threat-intel-service`, `graph-service`, Postgres.
- **Async deps:** Kafka.
- **AuthN/AuthZ:** internal JWT; per-event `tenant_id` preserved to detection row.
- **Failure:** model unavailable/timeout → `scoring_status = DEGRADED`, statistical fallback score, metric emitted, never drop; downstream sync dep down → degrade that contribution, record which inputs were missing.
- **Scaling:** horizontal by partition.
- **Observability:** detection rate, score distribution, `DEGRADED` counter, inference latency, per-input availability.

## ml-inference  (reqs 5, 11, 15)

- **Purpose:** serve registered models: Isolation Forest, autoencoder, GraphSAGE/GAT node & subgraph scorers, predictive threat model.
- **Owns (data):** nothing (models are immutable artifacts from MLflow/S3).
- **Consumes:** MLflow registry, S3 artifacts; sync inference requests.
- **Produces:** typed inference responses.
- **DB:** none (optional Redis for feature cache read).
- **External deps:** S3, MLflow.
- **Sync deps:** none (models in-process).
- **Async deps:** control topic for "new model version" hot-reload.
- **AuthN/AuthZ:** internal JWT; stateless w.r.t. tenant (caller passes features; no raw tenant data stored).
- **Failure:** model load failure at startup → service `not ready`; per-request model missing → typed error `MODEL_UNAVAILABLE` (caller degrades); inference timeout → 504.
- **Scaling:** horizontal; GPU pool in production (external requirement).
- **Observability:** per-model latency, request volume, load events, error types.

## ml-training  (reqs 5, 11, 15, 24, 34-deferred)

- **Purpose:** training pipelines + benchmark/evaluation harness. Dataset adapters (NSL-KDD, UNSW-NB15, CTU-13, EMBER, LANL, CICIDS2017). Batch.
- **Owns (data):** MLflow experiments/runs, model registry entries, S3 model artifacts, Postgres `benchmark_experiment` metadata.
- **Consumes:** datasets at `SM_DATASET_ROOT` (read-only), feature schemas.
- **Produces:** registered models, evaluation reports (S3), experiment rows.
- **DB:** Postgres (experiment metadata), MLflow, S3.
- **Sync/Async deps:** none (batch jobs / CronJobs).
- **AuthN/AuthZ:** operator-triggered; no tenant data (public research datasets).
- **Failure:** dataset missing → job fails fast with the missing path; non-deterministic run → rejected by reproducibility check (seed/version capture required).
- **Scaling:** job-level; GPU node pool (external).
- **Observability:** run status, duration, resource use; **metrics logged to MLflow only after real execution** — never pre-filled.

## threat-intel-service  (req 9)

- **Purpose:** IOC store-of-record; provider adapters (abuse.ch, OTX, …); enrichment API; confidence/freshness/expiry/provenance; provider-failure tolerance.
- **Owns (data):** Postgres `threat_indicator`, `threat_actor`, `ti_source`; Redis reputation cache.
- **Consumes:** external TI provider APIs (outbound adapter, TB-4).
- **Produces:** enrichment responses; Kafka `ti.updates` (new/expired IOCs).
- **DB:** Postgres, Redis.
- **External deps:** TI providers (all optional, feature-flagged).
- **Sync deps:** Postgres, Redis.
- **Async deps:** Kafka (produce), scheduled provider polls.
- **AuthN/AuthZ:** internal JWT; IOCs are platform-global unless tenant-submitted (then tenant-scoped).
- **Failure:** provider down/slow → serve cache, mark `freshness = STALE`, never fabricate; malformed provider response → drop + log, do not ingest.
- **Scaling:** horizontal read; single poller per provider.
- **Observability:** provider latency/error rate, cache hit ratio, IOC counts by freshness, poll success.

## mitre-service  (req 7)

- **Purpose:** ATT&CK technique/tactic catalog (versioned), technique-mapping engine, technique confidence, campaign alignment, heatmap data.
- **Owns (data):** Postgres `attack_technique`, `attack_tactic`, `technique_mapping`, `attack_matrix_version`.
- **Consumes:** ATT&CK STIX bundle (offline import); mapping requests from `detection-engine`, `ai-analyst-service`.
- **Produces:** mapping results, heatmap aggregates.
- **DB:** Postgres.
- **External deps:** none at runtime (catalog imported offline via a script).
- **Sync deps:** Postgres.
- **AuthN/AuthZ:** internal JWT; catalog global; mappings tenant-scoped.
- **Failure:** catalog not imported → mapping returns `UNMAPPED` + readiness warns; unknown technique id → typed error.
- **Scaling:** horizontal read, catalog is small.
- **Observability:** mapping volume, `UNMAPPED` rate, catalog version.

## ai-analyst-service  (reqs 14, 29, 32, 33, 36)

- **Purpose:** LLM provider adapters; evidence-grounded context builder; alert explanation; NL → `QueryPlan`; attack storytelling; root-cause analysis.
- **Owns (data):** Postgres `analyst_message`, `explanation`, `hunt_query`, `narrative`, `root_cause_analysis`.
- **Consumes:** LLM providers (TB-4); `graph-service`, `detection-engine`, `threat-intel-service`, `mitre-service`, `memory-service` (all sync, for evidence).
- **Produces:** explanations, query plans, narratives; audit records for every prompt/response/tool call.
- **DB:** Postgres.
- **External deps:** LLM providers.
- **Sync deps:** all evidence services, Postgres.
- **AuthN/AuthZ:** internal JWT + caller (user) context propagated; NL query authorization enforced on the derived `QueryPlan`, not the text; tool allow-list per task type.
- **Failure:** LLM down/timeout → typed `LLM_UNAVAILABLE`, no fabricated text; injection detected → refuse + audit; `QueryPlan` invalid → "cannot express", never raw query.
- **Scaling:** horizontal; provider rate limits are the ceiling.
- **Observability:** provider latency, token usage, tool-call counts, refusal reasons, injection-detection counter.

## agent-orchestrator  (reqs 30, 31)

- **Purpose:** multi-agent coordination (detection agent, TI agent, response agent); response engine with policy + authorization + approval + blast-radius + rollback + audit.
- **Owns (data):** Postgres `agent_task`, `response_action`, `response_policy`, `approval`.
- **Consumes:** Kafka `detections`, `agent.tasks`; `ai-analyst-service`, `graph-service` (sync); response-target adapters (TB-5).
- **Produces:** Kafka `agent.tasks`, `response.actions`; audit.
- **DB:** Postgres.
- **External deps:** response targets (EDR/firewall/SOAR) — adapters, default off.
- **Sync deps:** Postgres, `ai-analyst-service`.
- **Async deps:** Kafka.
- **AuthN/AuthZ:** internal JWT; agents run under constrained service principals with task-scoped tool allow-lists; **no autonomous privilege escalation**; `auto` mode gated (ADR-022).
- **Failure:** target adapter down → action `FAILED`, no partial state claimed, rollback plan retained; policy check fails → action `DENIED` + audit; approver absent → action `PENDING_APPROVAL` (never auto-proceeds in `approve_required`).
- **Scaling:** horizontal workers; per-action idempotency key.
- **Observability:** actions by state, approval latency, policy denials, rollback invocations, agent task queue depth.

## deception-service  (req 16)

- **Purpose:** honeypot/decoy control plane; attacker-interaction capture; adversary profiling. **Network-isolated** (TB-6).
- **Owns (data):** Postgres `decoy`, `decoy_interaction`, `adversary_profile` (deception-scoped).
- **Consumes:** decoy telemetry (isolated inbound).
- **Produces:** one-way export to `events.canonical` as `source.type = deception`.
- **DB:** Postgres (isolated schema/role).
- **External deps:** none.
- **Sync deps:** Postgres.
- **AuthN/AuthZ:** internal JWT; decoy data can never reach production response actions automatically.
- **Failure:** decoy down → interactions lost for that decoy (acceptable), alarmed; export blocked → local buffer + alarm.
- **Scaling:** per-decoy.
- **Observability:** decoy health, interaction rate, unique-source count.
- **Security invariant:** no route from the deception segment into production data planes or credentials.

## simulation-service  (reqs 17, 26, 35)

- **Purpose:** attack simulation (APT/ransomware/insider/brute-force), demo scenario engine (investor demos), security digital twin (blast-radius, stress test, resilience).
- **Owns (data):** Postgres `simulation`, `simulation_run`, `scenario`, `digital_twin_model`.
- **Consumes:** scenario definitions; twin environment representation.
- **Produces:** synthetic events labeled `source.type = simulation` / `metadata.simulation = true`; simulation results.
- **DB:** Postgres.
- **External deps:** none.
- **Sync deps:** Postgres.
- **AuthN/AuthZ:** role `analyst`+; simulations are tenant-scoped; **cannot emit `response.actions`**; all output labeled `SIMULATION`.
- **Failure:** isolated — a failed run cannot affect production detection state.
- **Scaling:** per-run workers.
- **Observability:** runs by status, generated-event counts, scenario coverage.
- **Security invariant:** never generates real-world traffic or real attacks; deterministic + reproducible.

## memory-service  (reqs 21, 37)

- **Purpose:** threat memory (behavioral pattern persistence), campaign evolution tracking, adversary fingerprinting + similarity search, cross-incident intelligence.
- **Owns (data):** Postgres (+ pgvector) `threat_memory`, `campaign`, `adversary_fingerprint`, `campaign_similarity`.
- **Consumes:** Kafka `detections`, `attack_chains`; `graph-service` (knowledge-graph reads).
- **Produces:** retrieval responses for `ai-analyst-service` / `agent-orchestrator`; Kafka `campaign.updates`.
- **DB:** Postgres + pgvector.
- **Sync deps:** Postgres, `graph-service`.
- **Async deps:** Kafka.
- **AuthN/AuthZ:** internal JWT; strictly tenant-scoped; cross-tenant similarity is **disabled by default** (only enabled via the federated mesh, ADR-023, with privacy controls).
- **Failure:** pgvector index unavailable → exact-match fallback + degrade flag; store down → retrieval returns `MEMORY_UNAVAILABLE`, analyst proceeds without memory context.
- **Scaling:** horizontal read; vector index sizing per tenant.
- **Observability:** retrieval latency, similarity-query volume, memory growth, fingerprint counts.

## reporting-service  (req 22)

- **Purpose:** executive summaries, automated SOC reports, compliance-ready reports. PDF generation to S3 + pre-signed download.
- **Owns (data):** Postgres `report`, `report_template`.
- **Consumes:** `detection-engine`, `graph-service`, `mitre-service`, `ai-analyst-service`, `memory-service` (sync, for content).
- **Produces:** PDF artifacts (S3), Kafka `report.generated`.
- **DB:** Postgres, S3.
- **Sync deps:** content services, Postgres.
- **Async deps:** Kafka, S3.
- **AuthN/AuthZ:** role-gated (`lead`/`tenant_admin` for compliance reports); tenant-scoped content only.
- **Failure:** content dep down → report marked `PARTIAL` listing missing sections, never fabricates content; S3 down → `report` row `FAILED`, retryable.
- **Scaling:** worker pool.
- **Observability:** report volume by type, generation latency, `PARTIAL`/`FAILED` counts.

## federation-service  (req 34) — DEFERRED (ADR-023)

- **Purpose:** federated-learning coordinator, distributed anomaly learning, poisoning defenses, aggregation, provenance, privacy boundaries.
- **Status:** contract stub only until a stable base model + hardened tenant isolation exist.
- **Owns (data):** (future) Postgres `federation_participant`, `model_update`, `aggregation_round`.
- **Security invariant (design-time):** participant trust establishment, update signing, differential-privacy / clipping on updates, no raw data exchange, aggregation-side anomaly detection for poisoning.

## api-gateway  (reqs 24, 18, 25 — the BFF)

- **Purpose:** the frontend's only backend. OIDC auth-code flow; session cookies; **deny-by-default RBAC enforcement**; request aggregation/projection; rate limiting; audit; pagination/filter/sort validation; API versioning; OpenAPI docs.
- **Owns (data):** Postgres read models/projections it maintains from Kafka (`detection_read`, `alert_read`, graph summaries), plus `sensor` registry, `user`, `role`, `permission`, `user_role`, `role_permission`, `tenant`, `audit_log` **(Phase 1 establishes the auth/tenant/RBAC subset here)**. (`identity_link` is owned by `normalization-engine`, not here.)
- **Consumes:** every internal service (sync); Kafka (projection consumers); OIDC IdP.
- **Produces:** typed HTTP responses; audit records; Kafka `user.events`.
- **DB:** Postgres (read+write for its owned tables), Redis (sessions, rate limits).
- **External deps:** OIDC IdP.
- **Sync deps:** all internal services, Postgres, Redis, IdP.
- **AuthN:** OIDC; httpOnly Secure SameSite session cookie; CSRF token; internal JWT minted for downstream calls, audience-scoped, carries `tenant_id` + `sub` + effective permissions hash.
- **AuthZ:** central policy module; every route declares `(permission, scope)`; deny-by-default; tenant predicate injected; role escalation impossible (roles resolved server-side from `user_role`).
- **Failure:** downstream service down → partial response with explicit `degraded` markers + correct status; IdP down → existing sessions valid until expiry, no new logins; Redis down → sessions fail (re-auth), read rate-limit opens with alarm.
- **Scaling:** horizontal, stateless (session state in Redis).
- **Observability:** per-route latency/error, authn failures, authz denials (by permission), rate-limit hits, downstream fan-out latency, audit write failures.

## notification-service  (req 13)

- **Purpose:** WebSocket gateway for live SOC updates (graph deltas, new detections, chain updates).
- **Owns (data):** ephemeral connection state (in-memory) + Redis consumer offset.
- **Consumes:** Redis fan-out streams (`sm:fanout:<tenant>`).
- **Produces:** WebSocket frames to browsers.
- **DB:** Redis.
- **Sync deps:** Redis; `api-gateway` (token introspection for the WS handshake).
- **AuthN/AuthZ:** WS handshake requires a valid session (cookie) + a short-lived WS token from `api-gateway`; subscription is tenant-locked to the session's tenant.
- **Failure:** Redis down → WS clients notified `degraded`, fall back to REST polling; slow client → bounded per-connection buffer, drop-oldest + `resync` hint.
- **Scaling:** horizontal; sticky sessions or shared Redis offset.
- **Observability:** active connections, messages/s, dropped-frame count, resync count.

---

## Dependency graph (sync, must stay acyclic)

```
frontend/web ──> api-gateway ──> { graph-service, detection-engine, threat-intel-service,
                                   mitre-service, ai-analyst-service, agent-orchestrator,
                                   memory-service, reporting-service, simulation-service }
frontend/web ──> notification-service ──> api-gateway (token introspection only)

ai-analyst-service ──> { graph-service, detection-engine, threat-intel-service,
                         mitre-service, memory-service }
detection-engine  ──> { ml-inference, mitre-service, threat-intel-service, graph-service }
agent-orchestrator ──> ai-analyst-service
reporting-service ──> { detection-engine, graph-service, mitre-service,
                        ai-analyst-service, memory-service }
normalization-engine ──> threat-intel-service
memory-service ──> graph-service
```

No service calls back into `api-gateway` for domain data (only
`notification-service` → token introspection, which is a leaf auth check, not a
cycle). Async (Kafka) edges are not part of the sync-cycle analysis.
