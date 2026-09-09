# SentinelMesh — Contracts

Versioned interface contracts: API, events, canonical entities, database
ownership, graph, ML I/O, AI/agent. The **implementation** of these contracts is
`packages/contracts-py` (Pydantic v2) → JSON Schema → `packages/contracts-ts`.

Contract status legend:

- **STABLE** — implemented, versioned, breaking change requires a new version.
- **DRAFT** — shape agreed at architecture level, not yet implemented; may change
  without a version bump until first implementation.
- **PLANNED** — owned by a later phase, listed for traceability only.

Nothing here asserts that any contract has been tested against a running system.

---

## 1. API conventions (**STABLE** for the Phase-1 auth/admin surface)

- Base path: `/api/v{major}` (start `/api/v1`). Only `major` in the path; minor
  changes are additive and backward-compatible.
- Auth: session cookie (browser) or internal JWT (service). Every non-public
  route declares `(permission, scope)`; deny-by-default.
- **Never** returns ORM/DB objects — only explicit response models.
- Request models: `extra='forbid'` (mass-assignment prevention), full validation.
- All list endpoints: cursor pagination (`?cursor=&limit=`, `limit` capped),
  validated `sort` (allow-list), validated `filter` (allow-list). No unbounded
  results.
- Every response carries `X-Request-Id`; every log line for the request carries
  `request_id` + `correlation_id`.
- Idempotency: unsafe methods that create resources accept `Idempotency-Key`
  header (stored 24h).
- Rate limiting: per principal + per route; `429` with `Retry-After`.

### 1.1 Canonical error contract (**STABLE**)

HTTP status is correct and specific. Body:

```json
{
  "error": {
    "code": "string_enum",          // machine-readable, stable
    "message": "human readable, safe for display, no internals",
    "request_id": "uuid",
    "correlation_id": "uuid",
    "details": [                      // optional, for validation errors
      { "field": "body.email", "issue": "invalid_format" }
    ]
  }
}
```

- `code` values (initial set): `unauthenticated`, `invalid_credentials`,
  `permission_denied`, `tenant_forbidden`, `not_found`, `validation_error`,
  `conflict`, `rate_limited`, `dependency_unavailable`, `degraded_result`,
  `payload_too_large`, `unsupported_media_type`, `internal_error`.
- **No** stack traces, SQL, driver messages, hostnames, or secret values ever.
- `SM_ENV != production` MAY add a top-level `debug` object; production MUST NOT.
- `internal_error` always `500` + generic message; real detail only in logs
  (with `request_id` for correlation).

### 1.2 Foundation endpoints (Phase 1 — **IMPLEMENTED** in `services/api-gateway`)

| Method | Path | Auth | Permission | Purpose |
|---|---|---|---|---|
| `GET` | `/healthz` | none | none | liveness — process up |
| `GET` | `/readyz` | none | none | readiness — required deps reachable |
| `GET` | `/health/deps` | internal | `ops:read` | per-dependency status detail |
| `GET` | `/api/v1/meta` | none | none | API version, build, `SM_ENV` |
| `POST` | `/api/v1/auth/login` | none (credentials) | none | local fallback login → session |
| `GET` | `/api/v1/auth/oidc/login` | none | none | begin OIDC auth-code flow |
| `GET` | `/api/v1/auth/oidc/callback` | none (state) | none | complete OIDC flow → session cookie |
| `POST` | `/api/v1/auth/logout` | session | none | destroy session |
| `GET` | `/api/v1/me` | session | none | current identity, tenant, effective permissions |
| `GET` | `/api/v1/admin/users` | session | `users:read` | list users in caller's tenant (paginated) |
| `POST` | `/api/v1/admin/users` | session | `users:create` | invite/create user in caller's tenant |
| `GET` | `/api/v1/admin/roles` | session | `roles:read` | list roles available to caller's tenant |
| `POST` | `/api/v1/admin/users/{id}/roles` | session | `roles:grant` | grant role (audited) |

Request/response schemas: `packages/contracts-py/src/sm_contracts/api/` (Phase 1).

---

## 2. Canonical event envelope (STABLE target — first implemented Phase 2)

Fields and rules: see `docs/architecture/event-model.md §1` and ADR-018.
Implementation: `sm_contracts.events.EventEnvelope[PayloadT]`.

`event_type` registry (grows per phase):

| `event_type` | `event_version` | payload model | producer | phase |
|---|---|---|---|---|
| `telemetry.network_flow` | 1 | `NetworkFlowPayload` | ingestion-gateway | 2 |
| `telemetry.auth_event` | 1 | `AuthEventPayload` | ingestion-gateway | 2 |
| `telemetry.dns_query` | 1 | `DnsQueryPayload` | ingestion-gateway | 2 |
| `telemetry.process_exec` | 1 | `ProcessExecPayload` | ingestion-gateway | 2 |
| `telemetry.file_access` | 1 | `FileAccessPayload` | ingestion-gateway | 2 |
| `event.canonical` | 1 | `CanonicalEventPayload` | normalization-engine | 2 |
| `graph.command` | 1 | `GraphCommandPayload` | stream-processor / detection-engine | 3 |
| `detection.raised` | 1 | `DetectionPayload` | detection-engine | 3 |
| `attack_chain.updated` | 1 | `AttackChainPayload` | stream-processor / detection-engine | 3 |
| `ti.indicator_updated` | 1 | `TiIndicatorPayload` | threat-intel-service | 3 |
| `agent.task` | 1 | `AgentTaskPayload` | agent-orchestrator | 7 |
| `response.action` | 1 | `ResponseActionPayload` | agent-orchestrator | 7 |
| `campaign.updated` | 1 | `CampaignPayload` | memory-service | 6 |
| `report.generated` | 1 | `ReportGeneratedPayload` | reporting-service | 8 |
| `user.event` | 1 | `UserEventPayload` | api-gateway | 1 |

The five `telemetry.*` payloads and `event.canonical` (`CanonicalEventPayload`)
are **implemented** in `sm_contracts.telemetry` and registered in
`EVENT_PAYLOAD_REGISTRY` (Phase 2, Unit 1). The whole pipeline runs against
Redpanda and is **CI-verified** (Phase 2 exit, run `34333269219`):
`ingestion-gateway` produces the five `telemetry.*` payloads onto `telemetry.raw`
(Unit 3); `normalization-engine` consumes them and produces `event.canonical`
onto `events.canonical` (Unit 4).

- The **five `telemetry.*` payloads are now STABLE** — a producer and a consumer
  both exercise them and Phase 2 has exited CI.
- **`event.canonical` stays STABLE target** — its first downstream consumer
  (`graph` / `detection`) is Phase 3.

`partition_key` for every producer is `sm_contracts.make_partition_key`
(`sha256(<tenant_id>:<primary_entity>)[:16]`, event-model.md §2). Every other
payload model is **DRAFT**.

### 2.1 Topic registry + versioned event types (Phase 3 — **STABLE**)

`sm_contracts.topics` is the definitive Kafka topic catalog — `TOPICS`
(name, partitions, key, retention, cleanup, producers, consumer groups) mirrors
event-model.md §3 one-to-one, and `EVENT_TYPE_TOPIC` / `topic_for_event_type`
map every `EventType` to its topic. Every producer and consumer addresses topics
through this module; string literals are a contract violation.

**Versioned event types.** `event_type` is the version identifier. A
backward-compatible payload change (optional fields only) keeps `event_type` and
bumps the envelope's `event_version` int. A breaking change adds a new
`EventType` member with a `.v2` suffix, its own `TOPICS` / `EVENT_TYPE_TOPIC`
entry, and runs in parallel with v1 during migration. `EVENT_TYPE_VERSION`
records the current major per type — all **1** today.

DLQ topic = `dlq_topic(t)` → `<t>.dlq`. Replay group = `replay_group(g)` →
`<g>-replay` (side-effecting adapters disabled; event-model.md §6).

---

## 3. Canonical entity contracts

Only entities with a Phase-1 implementation are **STABLE target**; the rest are
DRAFT/PLANNED and fully specified in `docs/architecture/data-model.md`.

| Entity | Owner service | Store | Contract status | Phase |
|---|---|---|---|---|
| `Tenant` | api-gateway | Postgres | **STABLE** | 1 |
| `User` | api-gateway | Postgres | **STABLE** | 1 |
| `Role` | api-gateway | Postgres | **STABLE** | 1 |
| `Permission` | api-gateway | Postgres | **STABLE** | 1 |
| `UserRole` / `RolePermission` | api-gateway | Postgres | **STABLE** | 1 |
| `Sensor` | api-gateway | Postgres | **STABLE** | 1 |
| `AuditRecord` | api-gateway (writer lib in common-py) | Postgres | **STABLE** | 1 |
| `Identity` / `IdentityLink` | normalization-engine | Postgres | DRAFT | 2 |
| `Asset` / `Host` / `IpAddress` / `Domain` / `Process` / `File` | graph-service (+ api-gateway attrs) | Neo4j + Postgres | DRAFT | 2–3 |
| `NetworkFlow` / `DnsQuery` / `AuthenticationEvent` / `EndpointEvent` / `FileAccessEvent` | (canonical event payloads) | Kafka | DRAFT | 2 |
| `Anomaly` / `Detection` / `ThreatScore` | detection-engine | Postgres | DRAFT | 3 |
| `SecurityAlert` / `Investigation` / `Incident` | api-gateway | Postgres | PLANNED | 3–4 |
| `ThreatIndicator` / `ThreatActor` | threat-intel-service | Postgres | DRAFT | 3 |
| `AttackTactic` / `AttackTechnique` / `TechniqueMapping` | mitre-service | Postgres | DRAFT | 3 |
| `AttackChain` / `AttackChainStage` | detection-engine / stream-processor | Postgres + Neo4j | DRAFT | 3 |
| `Explanation` / `Narrative` / `RootCauseAnalysis` / `AnalystMessage` / `HuntQuery` | ai-analyst-service | Postgres | PLANNED | 6 |
| `AgentTask` / `ResponseAction` / `ResponsePolicy` / `Approval` | agent-orchestrator | Postgres | PLANNED | 7 |
| `ThreatMemory` / `Campaign` / `AdversaryFingerprint` / `CampaignSimilarity` | memory-service | Postgres (+pgvector) | PLANNED | 6 |
| `Simulation` / `SimulationRun` / `Scenario` / `DigitalTwinModel` | simulation-service | Postgres | PLANNED | 9 |
| `Decoy` / `DecoyInteraction` / `AdversaryProfile` | deception-service | Postgres | PLANNED | 9 |
| `Report` / `ReportTemplate` | reporting-service | Postgres + S3 | PLANNED | 8 |
| `BenchmarkExperiment` | ml-training | Postgres + MLflow | PLANNED | 5 |

Every entity above is justified by a numbered requirement in
`REQUIREMENTS_TRACEABILITY.md`. No entity exists without one.

---

## 4. Database ownership (single-writer)

| Store / dataset | Sole writer |
|---|---|
| Postgres: `tenant,user,role,permission,user_role,role_permission,sensor,audit_log`, all `*_read` projections | api-gateway |
| Postgres: `identity_link` | normalization-engine |
| Postgres: `anomaly,detection,threat_score` | detection-engine |
| Postgres: `threat_indicator,threat_actor,ti_source` | threat-intel-service |
| Postgres: `attack_*` catalog + `technique_mapping` | mitre-service |
| Postgres: `attack_chain*` | detection-engine (+ stream-processor via topic) |
| Postgres: analyst artifacts | ai-analyst-service |
| Postgres: `agent_task,response_action,response_policy,approval` | agent-orchestrator |
| Postgres: `threat_memory,campaign,adversary_fingerprint` | memory-service |
| Postgres: `simulation*,scenario,digital_twin_model` | simulation-service |
| Postgres: `decoy*,adversary_profile` | deception-service |
| Postgres: `report,report_template` | reporting-service |
| Postgres: `benchmark_experiment` | ml-training |
| Neo4j (all) | graph-service |
| Redis (all namespaces) | per ADR-009 table |
| Kafka topics | per `event-model.md §3` |
| S3 buckets | ml-training (artifacts), reporting-service (reports), stream-processor (checkpoints) |

---

## 5. Graph contract (write path **IMPLEMENTED** Phase 4 Unit 2; read/query API Unit 3)

- Node labels, key properties, relationship types, and invariants:
  `docs/architecture/data-model.md`.
- Write path: only via `graph.commands` Kafka topic → `graph-service` (consumer
  group `graph-writer`). Command schema `sm_contracts.GraphCommandPayload`:
  `{ command_id, op: MERGE_NODE|MERGE_EDGE|SET_PROPS|PRUNE, tenant_id,
  observed_at, raw_event_id, label, key, props, start?, end? }` — for
  `MERGE_EDGE`, `label` is the relationship type and `start`/`end` are
  `GraphEndpoint{label, key}`. Idempotent by `command_id` (deterministic in the
  source event — `graph_command_id(...)`) + MERGE semantics.
- **Injection guard:** Cypher cannot parameterize a label or a relationship
  type, so `graph-service` validates every command's label against the frozen
  allowlist (`sm_contracts.GRAPH_NODE_LABELS` / `GRAPH_REL_TYPES`, pinned to
  `data-model.md`) before any query string is built. Everything else is a bound
  parameter. A non-allowlisted label is dead-lettered.
- **Apply semantics:** per-tenant node identity is the synthetic key
  `graph_node_uid(tenant_id, key) = "<tenant>:<key>"` (UNIQUE constraint); a
  relationship therefore can only join two nodes of the command's own tenant.
  Every node / relationship carries `tenant_id` + `first_seen` / `last_seen` +
  a `_watermark`; a command older than the watermark widens the seen-bounds but
  does not roll back properties (out-of-order safe). Missing endpoint nodes for
  an edge are created thin. A Neo4j outage → `TransientError` (retry, never drop).
- Result: `graph-service` emits `graph.events` (`sm_contracts.GraphEventPayload`:
  `{ command_id, op, outcome: APPLIED|DUPLICATE|STALE, tenant_id, observed_at,
  raw_event_id, label, nodes_written, relationships_written }`) for the read-model
  projection and notification fan-out.
- Producers of `graph.commands`: `stream-processor`'s `graph-update-emitter`
  (`events.canonical` → node upserts + one `actor -[REL]-> target` edge, `REL`
  from the canonical `kind`). `detection-engine` will also produce
  (`(:Detection)-[:INVOLVES]->…`).
- Read path: `graph-service` internal query API (**IMPLEMENTED** Phase 4 Unit 3):
  `GET /api/v1/graph/entity`, `/neighbors`, `/paths`. Service-JWT guarded
  (`verify_internal_token`, audience `graph-service`); **the tenant is the one in
  the verified token, never a request field**. `GraphRepository` builds every
  query parameterized — the only interpolated values are an allowlisted node
  label and an integer depth clamped to `[1, SM_NEO4J_TRAVERSAL_MAX_DEPTH]`
  (default cap 8; `neighbors` default 1, `paths` default 4). Row-capped
  (`SM_NEO4J_QUERY_MAX_ROWS`, default 1000; responses carry `truncated`),
  time-limited (`SM_NEO4J_QUERY_TIMEOUT_MS`). `_`-prefixed props and `uid` are
  stripped from responses. No caller supplies raw Cypher. Response models
  (`EntityResponse` / `NeighborsResponse` / `PathResponse`) are DRAFT, service-local.

---

## 6. ML I/O contract template (DRAFT — Phase 5)

Every model registered in MLflow declares, in `ml/models/<name>/CONTRACT.md`:

```
model_name:
model_version:              # semver; registry is source of truth
task:                       # anomaly_score | node_score | subgraph_class | forecast
input_schema:               # feature names, types, shapes, allowed ranges
feature_schema_version:     # ties to ml/features/
preprocessing_version:
output_schema:              # e.g. { score: float[0,1], contributing_features: [...] }
postprocessing:
inference_latency_budget_ms:
failure_behavior:           # what ml-inference returns on error (typed code)
evaluation:                 # dataset id + hash, metric definitions
                            # METRICS: NOT VERIFIED — REQUIRES REAL DATA / TRAINING ENVIRONMENT
reproducibility:            # seed, lib versions, git commit captured per run
```

No metric values appear until an experiment has actually run (ADR-024).

**Phase 5 Unit 2 — implemented in `packages/ml-py` (`sm_ml`):**

- `sm_ml.features` — `FEATURE_SCHEMA_VERSION` (currently `"1"`), a `FeatureSchema`
  (ordered, named, bounded float features) per `CanonicalKind`, and
  `extract_features(canonical) -> FeatureVector` (pure, deterministic, clamped).
- `sm_ml.preprocessing.Preprocessor` — versioned `(x - mean) / std`
  standardisation, serialisable, numpy-free.
- `sm_ml.models` — `AnomalyModel` protocol → `AnomalyScore` (`score`,
  `normalized_score` ∈ [0,1], `threshold`, `is_anomaly`, `model_version`,
  `contributing_features`). `StatisticalModel` (MAD z-score, stdlib-only, always
  available). `IsolationForestModel` (scikit-learn, `sm-ml[serving]`, loads a
  joblib artifact). `AutoencoderModel` (architecture fixed, `score` raises
  `ModelNotTrained`). `ModelUnavailable` / `ModelNotTrained` are the ADR-013
  degrade signals.
- `sm_ml.registry.ModelRegistry` — loads trained artifacts from
  `SM_ML_MODEL_DIR` (`<name>/<version>/{metadata.json, model.joblib|model.json}`).
  Missing directory = empty registry; `load` of an absent model raises
  `ModelUnavailable`.
- `ml/models/isolation_forest/CONTRACT.md`, `ml/models/autoencoder/CONTRACT.md` —
  the §6 fields filled in, `evaluation: METRICS: NOT VERIFIED — REQUIRES
  DATASET/TRAINING EXECUTION`.

---

## 7. AI / agent contracts (DRAFT — Phase 6/7)

### 7.1 `QueryPlan` (NL hunting — ADR-015)

```json
{
  "intent": "find_entity | list_related | path_between | timeline_for | detections_for | technique_usage",
  "parameters": { "...": "typed per intent" },
  "entity_refs": [{ "type": "identity|host|ip|domain|process", "value": "..." }],
  "time_range": { "from": "rfc3339", "to": "rfc3339" },
  "limits": { "max_depth": 4, "max_rows": 500 }
}
```

Closed schema. LLM produces this; server validates + authorizes + compiles to
parameterized Cypher. Unsupported request → `unsupported_query`, never a raw
query.

### 7.2 Explanation contract

```json
{
  "subject": { "type": "detection|attack_chain|incident", "id": "uuid" },
  "summary": "grounded natural language",
  "evidence": [{ "kind": "event|graph_path|ti_indicator|technique", "ref": "...", "provenance": "service+id" }],
  "confidence": "low|medium|high",
  "model": { "provider": "...", "model_id": "...", "prompt_hash": "..." },
  "generated_at": "rfc3339"
}
```

Every claim in `summary` must trace to an item in `evidence`. No `evidence` ⇒ no
explanation (returns `insufficient_evidence`).

### 7.3 `ResponseAction` contract

```json
{
  "action_id": "uuid",
  "type": "isolate_endpoint | block_ip | disable_user | create_firewall_rule | notify",
  "target": { "...": "typed" },
  "requested_by": "agent|user id",
  "policy_decision": "allowed|denied",
  "blast_radius": { "entities_affected": 0, "notes": "..." },
  "approval": { "required": true, "status": "pending|approved|rejected", "approver": null },
  "rollback_plan": { "steps": ["..."] },
  "mode": "suggest_only|approve_required|auto",
  "status": "suggested|pending_approval|executing|succeeded|failed|rolled_back|denied",
  "audit_ref": "uuid"
}
```

`mode=auto` invalid outside production + signed policy + allow-listed `type`.
Action without `rollback_plan` cannot be `auto`.

---

## 8. Frontend ↔ backend contract

- The frontend consumes **only** `api-gateway` REST (`/api/v1`) + the
  `notification-service` WebSocket.
- All types are generated from `contracts-ts` (no hand-authored domain types in
  the frontend).
- WebSocket messages: `{ type: "graph_delta|detection_new|chain_update|report_ready|degraded", tenant_id, payload, ts }`, tenant-locked to the session.
- The frontend must render `degraded_result` responses (partial data + markers),
  loading states, and the canonical error contract.

---

## Change log

| Date | Change | Phase |
|---|---|---|
| 2026-09-10 | **Temporal-intelligence engine** (Phase 8, Unit 2): `sm_ml.temporal` — `TemporalEvent` (id + source time + ingest time + entities + session), `EventTimeline` (a `bisect`-ordered stream: duplicates dropped by `event_id`, out-of-order events sorted on insert, clock skew clamped to `ingested_at + max_skew` and counted, missing events tolerated with `gaps()` reporting long silences — all order-independent, so the same set of events always yields the same timeline). `TemporalGraphState.from_timeline(...).at(t)` — the graph as it stood at any past moment, a pure fold; `snapshot.to_sample()` → a `GraphSample` so a graph model can score history. `build_progression(timeline, stage_fn)` → the furthest kill-chain `AttackStage` over time (never regresses, records every transition; `furthest_stage_at(t)`). `replay(timeline, from_t, to_t)` + `ReplayCursor` — deterministic, read-only, windowed re-emission (side-effecting adapters are disabled by the caller via `replay_group`). `stitch_sessions(sessions, link_within_seconds=)` — union-find over "shares an entity **and** is within N seconds", yielding `StitchedTrack`s (cross-session correlation). Config `SM_TEMPORAL_MAX_CLOCK_SKEW_SECONDS` / `SM_TEMPORAL_SESSION_LINK_SECONDS`. Standard-library, deterministic, no metric claimed. | 8 (Unit 2) |
| 2026-09-10 | **Graph-intelligence layer** (Phase 8, Unit 1): `sm_ml.graph` — `GraphSample` (deterministic, numpy-free: node features are pure functions of the edge set + a temporal window; edges sorted so the sample and any model output are order-independent; a malformed sample — unknown endpoint, duplicate id, non-finite feature — raises `ValueError`, never repaired). Versioned `GraphFeatureSchema` (`GRAPH_FEATURE_SCHEMA_VERSION = "1"`, 12 structural + temporal features + a node-type one-hot). Graph-model interface: `NodeAnomalyResult` / `SubgraphVerdict` / `ClusterResult`, each carrying `model_version` + an explicit `confidence`. Always-available (stdlib, deterministic) implementations: `StructuralGraphAnomaly` (MAD z-score with a stdev floor so a lone outlier in a uniform crowd is still caught), `SuspiciousSubgraphHeuristic`, `ConnectedComponentClusterer` / `LabelPropagationClusterer`. GNN boundary: `GnnNodeAnomalyModel` + `GRAPHSAGE_SPEC` / `GAT_SPEC` — `sm-ml[gnn]` (torch + torch-geometric) optional; torch absent → `GraphModelUnavailable`, checkpoint absent → `GraphModelNotTrained`, a serving layer degrades to the structural path. `GraphModelRegistry` (`SM_ML_GRAPH_MODEL_DIR`; empty → `available()` empty). `ml/models/{graphsage,gat,graph_anomaly}/CONTRACT.md` per §6. Config `SM_ML_SEED` / `SM_GRAPH_ANOMALY_Z` / `SM_TEMPORAL_*`. **No accuracy / AUC / precision / recall number anywhere — `METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`.** | 8 (Unit 1) |
| 2026-09-10 | **Phase 7 closed** (Unit 3): `correlation-engine` now also emits `graph.commands` for every updated chain — `MERGE_NODE :AttackChain {chain_id}` + `MERGE_EDGE (:AttackChain)-[:INVOLVES]->(subject node)` + `-[:MAPPED_TO]->(:AttackTechnique)` per technique (deterministic `command_id` per chain → `graph-writer` dedups). `mitre-service` now consumes `attack_chains` alongside `detections` (one group `mitre-mapping`, dispatch on `event_type`) → `technique_mapping` with `subject_type = attack_chain`. `detection-engine` **stops writing `threat_score`**; `correlation-engine` is the sole writer (an entity's score = its most-recently-updated chain's score; `weights_version = CHAIN_SCORE_VERSION`). Topic registry: `correlation` + `mitre-mapping` added as `detections` consumers, `correlation-engine` as the `attack_chains` producer + `mitre-mapping` as a consumer, `correlation-engine` as a `graph.commands` producer. Real-infra e2e (`test_chain_pipeline_e2e_pg.py`): an auth burst → detection → chain + one `threat_score` row + a `:AttackChain` node in Neo4j with `INVOLVES` → `:Identity` and `MAPPED_TO` → `:AttackTechnique`. Phase 7 exit report + §23 in `IMPLEMENTATION_STATE.md`; `REQUIREMENTS_TRACEABILITY` R6 → IMPLEMENTED, R8 updated. | 7 (close) |
| 2026-09-09 | **correlation-engine** (Phase 7, Unit 2): `services/correlation-engine` (port 8009, req 6). Consumes `detections` (group `correlation`); places each detection on the furthest kill-chain `AttackStage` its ATT&CK techniques imply (no mappable technique → `unknown`, never guessed; a `rule.ti.*` detection marks the chain threat-intel-corroborated); upserts one deterministic-id chain per `(tenant, subject)` per tumbling window + its `attack_chain_stage` rows (detection ids held as a set → at-least-once redelivery is a no-op; `min`/`max` timestamps → out-of-order safe; `ti_corroborated` monotonic). Recomputes `progression`, probabilistic `confidence` (`<= 0.95` — never certainty; grows with distinct ordered stages, discounted when stages ran backwards in time), `ChainStatus` (forming/active/dormant), and a **versioned deterministic** `score` (`CHAIN_SCORE_VERSION = "v1"`) over severity + anomaly + threat-intel + progression + confidence — asset-criticality and identity-risk are accepted as scorer inputs and renormalise the weighting when present (no registry feeds them in this phase). Emits `AttackChainPayload` on `attack_chains` (poison → `detections.dlq`; DB / produce failure → retried). Internal API `GET /api/v1/chains[/{chain_id}]` (service-JWT, audience `correlation-engine`, tenant from token). `DetectionPayload.subject_type` / `subject_id` now populated by `detection-engine`. Migration `0005` amended (additive columns `attack_chain_stage.max_detection_score`, `attack_chain.ti_corroborated`; `ChainStageModel` / `AttackChainModel` / `AttackChainPayload` gain the matching fields). No validated scoring performance is claimed. | 7 (Unit 2) |
| 2026-09-09 | **Attack-chain contracts + schema** (Phase 7, Unit 1): `sm_contracts.chains` — `AttackStage` (one per enterprise ATT&CK tactic, in kill-chain order, plus `unknown` as a real first-class value), `STAGE_ORDER`, `TACTIC_STAGE` (stable ATT&CK tactic ids) and `TECHNIQUE_STAGE` (only the techniques SentinelMesh's own rules emit — a small auditable map, **not** an ATT&CK-coverage claim); `stage_for_tactic` / `stage_for_technique` (unknown → `AttackStage.unknown`, never guessed) / `stages_for_techniques`. `ChainStatus` (forming / active / dormant — a chain is **never** auto-`confirmed`; confirmation is a human action). `ChainStageModel`, `AttackChainModel` (read DTO), `AttackChainPayload` on `attack_chains` (`EventType.attack_chain_updated`, now registered). `chain_dedup_key` (one chain per tenant+subject), `chain_window_start` (fixed **tumbling** window → chain ids stay deterministic under at-least-once redelivery and out-of-order events), `chain_id_for` (`uuid5`). `confidence` is bounded by `CONFIDENCE_CEILING = 0.95` — a chain never asserts certainty. `DetectionPayload` gained optional `subject_type` / `subject_id` (primary subject for correlation; populated by `detection-engine`). Alembic `0005` + `sm_common.db.chain_models` for `attack_chain` / `attack_chain_stage` (CHECK constraints from the contract enums, `(tenant, subject_type, subject_id, window_start)` unique, stage unique per chain, `ON DELETE CASCADE`). Status: **STABLE target** — first producer + consumer are Unit 2 (`correlation-engine`). | 7 (Unit 1) |
| 2026-09-09 | **Phase 6 closed** (Unit 5): TI enrichment is wired end to end and CI-VERIFIED (all four jobs, run `34366970151`) against real PostgreSQL + Redis + Redpanda + Neo4j. `normalization-engine` gains a `ThreatIntelEnricher` (feature-flagged `SM_TI_ENRICHMENT_ENABLED`, default off) that calls `threat-intel-service` `POST /api/v1/ti/enrich` for a canonical event's IP / domain / hash entities and writes `canonical.enrichment["threat_intel"]` (`provider`, `as_of`, `matches` — genuine non-expired hits only; a TI-service outage leaves the key absent and never fails the event, R2). `detection-engine` gains rule `rule.ti.known_bad_indicator` — fires on a real TI match, severity from the match reputation (`>= 0.75` → high), `technique_ids = ()` (a TI hit is not itself a technique; mapping stays with `mitre-service`), evidence is an `EvidenceItem(kind=ti_indicator)` carrying the matches + provenance. `test_ti_enrichment_chain_pg.py` proves the full chain and the no-match / no-fabrication path. Phase 6 exit report + §23 review in `IMPLEMENTATION_STATE.md`; `REQUIREMENTS_TRACEABILITY` R7 / R9 → IMPLEMENTED. **No ATT&CK data ships; no coverage claim beyond the imported catalog; no threat intelligence fabricated.** | 6 (close) |
| 2026-09-09 | **TI provider adapters** (Phase 6, Unit 4): `sm_ti_service.providers` — `ThreatIntelProvider → ProviderAdapter → ExternalProvider`. The adapter supplies per-attempt timeout, backoff retry (HTTP 429 → longer backoff), malformed-row drop (never ingested), and outage → `ProviderResult(ok=False, [])` (TB-4: never fabricate — the store keeps serving what it has and freshness ages to `STALE`). `FixtureProvider` is `source_kind=FIXTURE` / `provider="fixture"`. `abusech` / `otx` adapters match the public URLhaus / OTX shapes, are feature-flagged **off** (`SM_TI_PROVIDERS` empty → no outbound calls). `ProviderPoller` (one per process) runs enabled providers, upserts, emits `ti.updates`, records `ti_source.last_poll_status`. | 6 (Unit 4) |
| 2026-09-09 | **threat-intel-service** (Phase 6, Unit 3): `services/threat-intel-service` (req 9, TB-4). IOC store of record (`threat_indicator` etc.), dedup on `indicator_dedup_key` (global vs tenant-submitted), rule-based deterministic `reputation_score`, freshness derived on read (`freshness_for` vs `SM_TI_DEFAULT_TTL_SECONDS`). Never fabricates: a value that fails `normalize_indicator_value` is rejected (422); every indicator carries a `Provenance`; fixture data is `source_kind = FIXTURE`. Internal service-JWT API (audience `threat-intel-service`): `POST /api/v1/ti/enrich` (batch → `EnrichmentMatch` per input, matched only if present and not expired), `GET`/`POST /api/v1/ti/indicators`. Produces `TiUpdatePayload` on `ti.updates` for add/update; a background expiry sweep emits `expired` once. Global-IOC events use `PLATFORM_TENANT` (`uuid(int=0)`) on the envelope; scope is `payload.tenant_id` (nullable). Response models DRAFT / service-local. | 6 (Unit 3) |
| 2026-09-09 | **mitre-service** (Phase 6, Unit 2): `services/mitre-service` (req 7). Postgres catalog store; `scripts/import_attack_stix.py` + `sm_mitre_service.stix` (STIX 2.1 bundle → tactics / techniques / matrix version + sha256 — **no ATT&CK data ships**; a labelled fixture bundle drives tests). Rule-based `MappingEngine` — validates a detection's candidate `technique_ids` against the imported catalog (unknown / deprecated → `unmapped`, never guessed), enriches known ids with name + tactic + matrix version, upserts `technique_mapping` (`source = rule`). Consumes `detections` (group `mitre-mapping`). Internal API: `GET /api/v1/mitre/{techniques,heatmap}`, `POST /api/v1/mitre/map`. `/readyz` flags an empty catalog. Response models DRAFT / service-local. Never claims coverage beyond the imported catalog. | 6 (Unit 2) |
| 2026-09-09 | **Threat-intel + MITRE contracts + schema** (Phase 6, Unit 1): `sm_contracts.mitre` — `AttackTactic` / `AttackTechnique` / `AttackMatrixVersion` (records exactly what an import produced — no coverage claim beyond it) / `TechniqueMapping` / `TechniqueMatch`; `MappingConfidence` / `MappingSource` (rule/graph/feature/llm/analyst — LLM never authoritative alone) / `MappingSubjectType`. `sm_contracts.threatintel` — `ThreatIndicator` (with mandatory `Provenance` + `source_kind`) / `ThreatActor` / `TiCampaign` / `TiSource` / `EnrichmentMatch`; `TiUpdatePayload` on `ti.updates` (`EventType.ti_indicator_updated`); `IndicatorType` / `IndicatorFreshness` (derived, not asserted) / `TiConfidence` / `TiSourceKind` (incl. `FIXTURE`) / `TiUpdateAction`; `normalize_indicator_value` (rejects malformed — TB-4), `indicator_dedup_key` (global vs tenant), `freshness_for`. Alembic `0004` + models for `attack_tactic` / `attack_technique` / `attack_matrix_version` / `technique_mapping` / `threat_indicator` / `threat_actor` / `ti_campaign` / `ti_source`. Status: **STABLE target**. | 6 (Unit 1) |
| 2026-09-08 | Initial contract set authored (Phase 0). API conventions, error contract, envelope, entity list, ownership, graph/ML/AI contract skeletons. | 0 |
| 2026-09-09 | Telemetry payload contracts implemented (Phase 2, Unit 1): `NetworkFlowPayload`, `AuthEventPayload`, `DnsQueryPayload`, `ProcessExecPayload`, `FileAccessPayload`, `CanonicalEventPayload` + `EntityRef`; all registered in `EVENT_PAYLOAD_REGISTRY` and `SCHEMA_MODELS` (34 JSON Schema files). Sensor payloads validate IPs, bound free-text fields and normalize case; the canonical payload keeps `raw_event_id` lineage and requires `actor`/`target` to appear in `entities`. Status: STABLE target. | 2 (Unit 1) |
| 2026-09-09 | `ingestion-gateway` implemented (Phase 2, Unit 2): sensor-authenticated `POST /api/v1/ingest/{source_type}` + `/batch`. The service **produces** the five `telemetry.*` payloads as concrete `EventEnvelope[...]` values — `tenant_id`, `source.sensor_id` and `source.type` come from the authenticated `SensorIdentity`, never the body; `occurred_at` is lifted from the payload. `SensorAuth` (`sm_common.security`) added and integration-verified. | 2 (Unit 2) |
| 2026-09-09 | Event bus live (Phase 2, Unit 3): `sm_common.bus.EventBusProducer` (aiokafka, idempotent, `acks=all`) + Kafka sinks. The five `telemetry.*` payloads are now on `telemetry.raw` for real (verified against Redpanda); malformed bodies on `telemetry.raw.dlq`. `partition_key` conformed to `event-model.md` = `sha256(<tenant_id>:<primary_entity>)[:16]`. | 2 (Unit 3) |
| 2026-09-09 | `normalization-engine` implemented (Phase 2, Unit 4): consumes `telemetry.raw`, deterministic per-source mapping → `CanonicalEventPayload`, produces `event.canonical` on `events.canonical` (verified against Redpanda). Canonical envelope keeps `raw_event_id` lineage; `correlation_id` / `source` carried from the raw event. Poison records → `telemetry.raw.dlq` wrapped per §5. `sm_common.bus.EventBusConsumer` + `dlq_payload` added; `make_partition_key` extracted to `sm_contracts`. `event.canonical` now producer+consumer exercised; STABLE target holds pending Phase 2 CI. | 2 (Unit 4) |
| 2026-09-09 | Phase 2 §23 review: (1) the canonical `event_id` is now `uuid5(raw_event_id)` — deterministic, so at-least-once redelivery re-emits the same id (event-model.md §4). (2) `DnsQueryPayload.answers` now rejects an empty-string answer (was a silent downstream DLQ). (3) ingestion-gateway frees the `X-Sensor-Event-Id` dedup mark on a 4xx so a corrected retry is not suppressed. | 2 (review) |
| 2026-09-09 | **Phase 2 exit — CI green** (GitHub Actions run `34333269219`). The five `telemetry.*` payloads promoted **DRAFT → STABLE** (a producer and a consumer both exercise them). `event.canonical` stays **STABLE target** — first downstream consumer is Phase 3. | 2 (close) |
| 2026-09-09 | **Topic registry** (Phase 3, Unit 1): `sm_contracts.topics` — `TOPICS` mirrors event-model.md §3; `EVENT_TYPE_TOPIC` / `topic_for_event_type` map every `EventType`; `dlq_topic` / `replay_group` helpers; `EVENT_TYPE_VERSION` (all v1). The "versioned event types" policy is documented (§2.1). `ingestion-gateway` / `normalization-engine` refactored to the registry. STABLE. | 3 (Unit 1) |
| 2026-09-09 | **`GraphCommandPayload`** implemented (Phase 3, Unit 3): `sm_contracts.graph` — `command_id` / `op` / `tenant_id` / `observed_at` / `raw_event_id` / `label` / `key` / `props` / `start` / `end` (§5). Registered for `EventType.graph_command`; `EventEnvelope_GraphCommand` + `GraphCommandPayload` JSON Schemas. `stream-processor`'s `graph-update-emitter` produces them from `events.canonical`; `command_id` is deterministic (`graph_command_id`). Status: **STABLE target** — the first consumer (`graph-writer`) is Phase 4. | 3 (Unit 3) |
| 2026-09-09 | **Neo4j graph foundation** (Phase 4, Unit 1): `sm_common.graph` (async driver wrapper, per-query timeout, outage→`GraphUnavailableError`), the label/relationship allowlist in `sm_contracts.graph` (`GRAPH_NODE_LABELS` / `GRAPH_REL_TYPES` / `graph_node_uid`, pinned to `data-model.md`), and the versioned Cypher schema (`migrations/neo4j/0001_schema.cypher` + `apply_pending` runner). CI-green (run `34346140544`). | 4 (Unit 1) |
| 2026-09-09 | **Graph write path** (Phase 4, Unit 2): `services/graph-service` consumes `graph.commands` (group `graph-writer`) and applies each `GraphCommandPayload` as a parameterized idempotent MERGE — label allowlist-validated, `command_id`-deduped, out-of-order safe (`_watermark`), tenant invariants by construction, missing endpoints created, Neo4j outage → `TransientError`. New `GraphEventPayload` (`outcome: APPLIED\|DUPLICATE\|STALE` + counts) on `graph.events`; `EventType.graph_event`; `EventEnvelope_GraphEvent` + `GraphEventPayload` JSON Schemas (38 files). `GraphCommandPayload` promoted **STABLE target → STABLE** (producer and consumer both exercise it). INTEGRATION VERIFIED against real Neo4j 5. | 4 (Unit 2) |
| 2026-09-09 | **Graph read path** (Phase 4, Unit 3): `graph-service` internal query API — `GET /api/v1/graph/{entity,neighbors,paths}`, service-JWT guarded, tenant from the token. `GraphRepository` — parameterized only (label allowlisted, depth an int clamped to `SM_NEO4J_TRAVERSAL_MAX_DEPTH`), row-capped (`SM_NEO4J_QUERY_MAX_ROWS`), `_`/`uid` props stripped. Response models DRAFT / service-local. INTEGRATION VERIFIED against real Neo4j 5 (bounded neighbourhood, shortest path, cross-tenant reads return nothing). | 4 (Unit 3) |
| 2026-09-09 | **Phase 5 closed** (Unit 5): the detection pipeline is INTEGRATION VERIFIED against real PostgreSQL (`test_detection_pipeline_pg.py` — burst → `detection` + `security_alert` with grounded evidence, dedup, tenant isolation) and CI-green on a clean runner (run `34358654888`). Phase 5 exit report + §23 review in `IMPLEMENTATION_STATE.md`. Trained models + any accuracy figure: `NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`. | 5 (close) |
| 2026-09-09 | **detection-engine** (Phase 5, Unit 4): `services/detection-engine` — consumes `events.canonical` (group `detection`), system of record for `detection` / `anomaly` / `threat_score` / `security_alert`, produces `DetectionPayload` on `detections`. Per event: features → adaptive per-`(tenant, kind)` statistical anomaly (rolling window) + optional `ml-inference` contribution (failure → `DEGRADED`, ADR-013) + six deterministic rule detectors → deterministic composite score (`WEIGHTS_VERSION`, renormalised over present components) → a detection (deterministic id, upsert) only above threshold or on a `medium`+ rule, every claim an `EvidenceItem` → alert at `high`/`critical`. No accuracy / latency figure produced or stored. `DetectionPayload` promoted **STABLE** (producer + the `detections` topic contract are now exercised). | 5 (Unit 4) |
| 2026-09-09 | **ml-inference service** (Phase 5, Unit 3): `services/ml-inference` (ADR-013). Internal, service-JWT API (audience `ml-inference`): `POST /api/v1/infer/{model}` (request `{kind, feature_schema_version, features:[float]}`, response the `AnomalyScore` shape), `GET /api/v1/models`. `ModelHost` lazy-loads from `sm_ml.ModelRegistry` and caches. A missing / unloadable / serving-deps-absent model → HTTP 503 `dependency_unavailable` with `MODEL_UNAVAILABLE: <model>` + a `model` detail; inference exceptions map the same. `/readyz` always ready (models optional). Request / error / latency / load metrics. Request+response models DRAFT / service-local. | 5 (Unit 3) |
| 2026-09-09 | **sm-ml layer** (Phase 5, Unit 2): see §6. | 5 (Unit 2) |
| 2026-09-09 | **Detection contracts + schema** (Phase 5, Unit 1): `sm_contracts.detection` — `DetectionPayload` (thin `detections`-topic projection, registered for `EventType.detection_raised`), `EvidenceItem` / `EvidenceKind` (every detection claim is grounded, Constitution §3), `detection_dedup_key` / `detection_id_for` (deterministic, window-bucketed). DTOs `Detection` / `Anomaly` / `ThreatScore` / `SecurityAlert`; enums `Severity` / `DetectorKind` / `AnomalyMethod` / `ScoringStatus` / `DetectionStatus` / `AlertStatus` / `ThreatSubjectType`. Alembic `0003` + SQLAlchemy models for the four `detection-engine` tables (system of record). 3 new JSON Schemas' worth of models (41 files). No accuracy / latency number anywhere. Status: **STABLE target** — first producer + consumer are Units 3–4. | 5 (Unit 1) |
| 2026-09-09 | **Phase 4 closed** (Unit 4): the graph pipeline is end-to-end verified against real Redpanda + real Neo4j (`test_graph_pipeline_e2e.py` — canonical event → `stream-processor` → `graph.commands` → `graph-service` → Neo4j → `GraphRepository` query round-trip; `graph.events` `outcome: APPLIED`). §23 review recorded in `IMPLEMENTATION_STATE.md`. `graph.events` / `GraphEventPayload` stays **STABLE target** — its first consumer (`api-projection`) is a later phase. | 4 (close) |
| 2026-09-08 | Phase-1 auth/admin API surface **implemented** in `services/api-gateway` and its contracts promoted DRAFT → **STABLE**: API conventions, the canonical error contract, the foundation endpoint set (§1.2), and the `Tenant`/`User`/`Role`/`Permission`/`UserRole`/`RolePermission`/`Sensor`/`AuditRecord` entity contracts. Cursor pagination, CSRF header (`X-CSRF-Token`) and the session cookie names are part of the stable surface. | 1 (Unit 4) |
| 2026-09-08 | `packages/contracts-py` implements the canonical `EventEnvelope`, the `ErrorResponse` contract (`HTTP_STATUS_BY_CODE`), Phase-1 entity DTOs (`Tenant`, `User`, `Role`, `Permission`, `RolePermission`, `UserRoleGrant`, `Sensor`, `AuditRecord`), Phase-1 API models, and shared enums. JSON Schema generated to `packages/contracts-ts/schemas/` via `scripts/gen_contracts.py`. Status of these contracts: **STABLE target** — promoted to STABLE when the Phase-1 endpoints that use them ship. `identity_link` ownership corrected to `normalization-engine` (Phase 2) — see `architecture/consistency-review.md`. | 0 (close) |
