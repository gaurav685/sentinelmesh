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
| `Explanation` / `RootCauseAnalysis` / `AnalystMessage` / `HuntQuery` | ai-analyst-service | Postgres | PLANNED | 6 |
| `Narrative` | ai-analyst-service | Postgres | **STABLE** (IMPLEMENTED P14) | 14 |
| `AgentTask` / `ResponseAction` / `ResponsePolicy` / `Approval` | agent-orchestrator | Postgres | PLANNED | 7 |
| `ThreatMemory` / `Campaign` / `AdversaryFingerprint` | memory-service | Postgres (+pgvector) | **STABLE** (IMPLEMENTED P13) | 13 |
| `Simulation` / `SimulationRun` / `Scenario` / `DigitalTwinModel` | simulation-service | Postgres | PLANNED | 9 |
| `Decoy` / `DecoyInteraction` / `AdversaryProfile` | deception-service | Postgres | PLANNED | 9 |
| `Report` / `ReportTemplate` | reporting-service | Postgres + S3 | **STABLE** (IMPLEMENTED P14) | 14 |
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
| Postgres: `hunt_query` (threat-hunting history) | api-gateway |
| Postgres: `decoy,decoy_interaction` (deception registry) | simulation-service |
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
- **Threat-hunting query path (`POST /api/v1/graph/hunt`, **IMPLEMENTED** Phase 11
  Unit 1):** the caller sends a `sm_contracts.QueryPlan` — a **closed schema**: a
  `HuntIntent` ∈ {`find_entity`, `list_related`, `path_between`, `detections_for`,
  `chains_for`, `indicator_sightings`, `technique_usage`} over typed
  `EntitySelector`s + `QueryLimits`. `graph-service` `hunt.py` `validate_plan`
  rejects anything outside the capability set (wrong selector count/type for the
  intent, an unknown `rel_type`, `rel_types` on a non-`list_related` intent) →
  422. `compile_plan` maps the intent to **one constant parameterized Cypher
  template**; the only interpolations are a node label (checked against
  `GRAPH_NODE_LABELS`), relationship-type names (checked against
  `GRAPH_REL_TYPES`), and an integer depth clamped to `SM_HUNT_MAX_DEPTH` (3).
  Every entity value the caller supplied is a `$`-parameter — it never reaches
  the query text. The tenant is `$tenant` from the verified token — `QueryPlan`
  has **no tenant field**, so a plan cannot widen scope. Read-only, row-capped by
  `SM_HUNT_MAX_ROWS` (200) on top of the plan's own limit. `HuntResult.cypher_fingerprint`
  is the sha256 of the template text (not the params) — it proves which of the
  fixed queries ran and leaks nothing. A non-existent (hallucinated) entity is an
  honest empty result, not an error.

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

### 7.1 `QueryPlan` (NL hunting — ADR-015; **IMPLEMENTED** Phase 11)

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

**As implemented:** `sm_contracts.QueryPlan` — `intent` ∈ {`find_entity`,
`list_related`, `path_between`, `detections_for`, `chains_for`,
`indicator_sightings`, `technique_usage`}, `selectors: [EntitySelector{type, value}]`
(1, or exactly 2 for `path_between`), `rel_types` (allow-list, `list_related`
only), `time_range?`, `limits: {max_depth ≤ 4, max_rows ≤ 500}`. `ai-analyst`'s
`HuntPlanner` parses the LLM's JSON into this model — the model output is **never**
used as a query, and a plan it cannot produce is `PlanResponse(supported=false)`.
`graph-service` `hunt.py` `validate_plan` + `compile_plan` turn it into one of a
fixed set of parameterized Cypher templates (see §5). `api-gateway`
`POST /api/v1/soc/hunt` is the browser entry point (`hunt:query` + CSRF; tenant
from the session, never a body field); `hunt_query` (migration `0006`) is the
append-only history.

### 7.2 Explanation contract (**IMPLEMENTED** Phase 10, Unit 3 — `sm_contracts.Explanation`)

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

**As implemented:** `sm_contracts.ExplainRequest` (subject + task + a list of
`EvidenceRef`) → `sm_contracts.Explanation` (`summary`, `cited_refs`,
`confidence`, `recommendations`, `model` = `{provider, model_id, prompt_sha256,
from_live_provider}`, `generated_at`, `degraded`, `degraded_reason`,
`evidence_flagged`). `services/ai-analyst` validates that every `[ref]` cited by
`summary` is a real evidence ref (one repair attempt, then it falls back to a
deterministic factual template with `degraded=true`). `recommendations` is a
fixed vetted per-subject list — **never model-authored** — so an injection cannot
turn it into an instruction. `api-gateway` `GET /api/v1/soc/detections/{id}/explanation`
gathers the evidence from the tenant-scoped detection record and proxies.

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

### 7.4 LLM provider boundary (`sm_ai` — **IMPLEMENTED** Phase 10, Unit 1)

The LLM is an **untrusted** component. `packages/ai-py` (`sm_ai`) is the only
path to a model:

- **Messages** (`sm_ai.messages`) — provider-neutral `LlmRequest` /
  `LlmResponse` / `ToolSpec` / `ToolCall` / `TokenUsage`. `LlmResponse.from_live_provider`
  is `True` **only** when an adapter actually reached a remote provider; nothing
  in SentinelMesh may describe output as "verified against a live LLM" off a
  `False`.
- **Providers** (`sm_ai.provider` / `sm_ai.adapters`) — `LlmProvider` protocol;
  `DeterministicAdapter` (network-free, reproducible, the default with no
  credentials and what every test uses); `HttpLlmBoundary` (Anthropic Messages
  API shape — raises `ProviderUnavailable` with no `SM_LLM_API_KEY`, never
  executed against a live endpoint in this project).
- **Client** (`sm_ai.client.LlmClient`) — the only entry point the analyst /
  agents use. Enforces a per-call prompt-token ceiling **before** any network
  I/O (`SM_LLM_MAX_PROMPT_TOKENS`), an optional per-run `RunBudget`
  (`SM_AGENT_MAX_LLM_TOKENS_PER_RUN`), a wall-clock timeout
  (`SM_LLM_REQUEST_TIMEOUT_S`), cooperative cancellation, transient-only bounded
  retry (`SM_LLM_MAX_RETRIES` — a `ProviderRefused` is never retried), and one
  `AuditEvent` per attempt carrying `prompt_sha256` + `purpose` + usage +
  outcome — **never the raw prompt**.
- Orchestration ceilings for later units: `SM_AGENT_MAX_STEPS` /
  `SM_AGENT_MAX_TOOL_CALLS` / `SM_AGENT_WALL_CLOCK_TIMEOUT_S`.

### 7.5 Authorized tools + evidence (`sm_ai` — **IMPLEMENTED** Phase 10, Unit 2)

- **Tools** (`sm_ai.tools` / `sm_ai.registry`) — every capability is a `Tool`
  with an explicit Pydantic `args_model` (the model only ever sees its JSON
  Schema), an optional `required_permission: PermissionCode`, and input + output
  validation. `ToolRegistry` is **deny-by-default**: `specs_for(principal)`
  offers only the tools that principal is authorized for; `invoke(call, ctx)`
  re-checks — tool exists (`UnknownToolError`) → principal holds the permission
  (`ToolAuthorizationError` — *the LLM having asked is irrelevant*) → arguments
  valid (`ToolInputInvalid`) → run → output valid (`ToolOutputInvalid`) — and
  emits a `ToolInvocationRecord` (tool, principal, tenant, correlation id,
  outcome, authorized?) for **every** path.
- **Evidence** (`sm_ai.evidence` / `sm_ai.sanitize` / `sm_ai.prompt`) — the AI
  analyst answers only from evidence the platform gathered. `EvidenceBuilder`
  renders SentinelMesh-produced strings (`trusted=True`: rule ids, scores,
  catalog technique ids) plainly and **fences everything telemetry- or
  third-party-derived** (`fence_untrusted` — delimiter lookalikes neutralised,
  per-item + total size caps → `ContextPoisoningDetected`). `scan_for_injection`
  records override-pattern hits per evidence ref. `build_grounded_messages`
  **guarantees the evidence is only ever a `user` turn** — instructions stay in
  `system`, which tells the model that fenced content is inert data.

### 7.6 Multi-agent defense (`sm_ai.agents` — **IMPLEMENTED** Phase 10, Unit 4)

- **Agents** (`sm_ai.agents`) — an `AgentSpec` is a name + a fixed system prompt
  + a **tool allow-list**. `run_agent(spec, task, evidence, …)` drives the LLM
  loop under `AgentLimits`: `max_steps`, `max_tool_calls`, `wall_clock_s`, and a
  cumulative-token `RunBudget`, plus a cancellation `Event` checked every step.
  `DETECTION_AGENT` / `THREAT_INTEL_AGENT` / `RESPONSE_AGENT`. An agent **cannot
  spawn another agent** (the runner takes a flat spec, not a graph, and there is
  no tool for it) and **cannot execute** anything. A tool outside the spec's
  allow-list, or one the principal is not authorised for, is refused mid-run and
  returned to the model as an error tool-result — the run continues. A tool
  exception is caught and returned as `error: …`, not propagated. The agent
  principal holds **no standing permissions**.
- **Action gate** (`sm_ai.action_gate`) — `RESPONSE_AGENT` emits
  `ProposedAction`s; the gate is a pure function of `(response_mode,
  approval_required, is_production, policy_signed, action.reversible)`:
  `suggest_only` → `denied`; `allowed` requires `auto` **and** no approval
  requirement **and** production **and** a signed policy **and** a reversible
  action; everything else → `approval_required`. With the shipped
  `SM_RESPONSE_MODE=suggest_only` + `SM_RESPONSE_APPROVAL_REQUIRED=true`, a
  proposal is **never** `allowed`. An LLM proposing an action is never
  sufficient — this is the R31/§7.3 boundary.
- **Contract** — `sm_contracts.AgentRunRequest` (agent name + subject +
  `EvidenceRef` list) → `AgentRunResult` (`status`, `steps_used`,
  `tool_calls_used`, `tokens_spent`, `findings`, `proposed_actions` each with a
  `decision` = the gate verdict, `generated_at`). `services/ai-analyst`
  `POST /api/v1/agents/run` (internal JWT). No live LLM → `status="failed"`,
  `detail="llm_unavailable"`, never a 500.

---

## 8. Frontend ↔ backend contract

- The frontend consumes **only** `api-gateway` REST (`/api/v1`). The
  `notification-service` WebSocket is the intended realtime channel; **not built
  yet** — Phase 9 realtime is an honest client poll with a "last updated"
  indicator (`LiveBadge`), never a streaming claim.
- All types are generated from `contracts-ts` (no hand-authored domain types in
  the frontend). `contract.test.ts` fails the build if a regenerated type no
  longer accepts a known-good fixture.
- Frontend authorization is **display-only** (`hasPermission` filters nav +
  hides controls). Every `/api/v1/*` route enforces `require_permission` in
  `api-gateway`. `middleware.ts` only redirects a request with no session cookie.
- WebSocket messages (when built): `{ type: "graph_delta|detection_new|chain_update|report_ready|degraded", tenant_id, payload, ts }`, tenant-locked to the session.
- The frontend must render `degraded_result` responses (partial data + markers),
  loading states, and the canonical error contract.

---

## Change log

| Date | Change | Phase |
|---|---|---|
| 2026-09-12 | **Baseline IDS comparison: a real Isolation Forest vs. the statistical baseline** (Phase 15, Unit 3; R24): no contract changed this unit. `sm_ml_training.benchmark.harness.run_benchmark` gained a `model` parameter — `"isolation_forest"` trains scikit-learn's `IsolationForest` directly in the harness (new `ml-training[benchmark]` extra pulling `sm-ml[serving]`, now installed in all three CI jobs) on the same benign-only NSL-KDD train rows, scored one row at a time against the same test split (matching `sm_ml.models.AnomalyModel`'s real one-event-at-a-time serving contract, not an unrealistic batch score). Absent the extra, `run_benchmark(model="isolation_forest")` raises `ModelUnavailable` — verified with a real test blocking the import via `monkeypatch`, mirroring `sm_ml.graph.models.gnn`'s existing optional-dependency test pattern. **Real, executed comparison** against the same NSL-KDD files/hashes as Unit 2: Isolation Forest → ROC-AUC 0.935499, precision 0.961297, recall 0.621289, F1 0.754769, false-positive rate 0.033055, mean detection latency 24.836165 ms/row — vs. the statistical baseline's 0.639039 AUC / 0.649367 FPR / 0.054062 ms/row: substantially more accurate (AUC +0.296, FPR 20x lower), ~460x slower per row — a real, measured accuracy/latency tradeoff. CICIDS2017/UNSW-NB15/LANL local availability re-checked and unchanged (still not usable in labeled form); no adapter built, no number claimed for any of them. 4 new unit tests. | 15 (Unit 3) |
| 2026-09-12 | **Tabular IDS benchmark harness core + a real NSL-KDD run** (Phase 15, Unit 2; R24): no contract changed this unit. New `sm_ml_training.benchmark` — `nsl_kdd.py` (dataset adapter; categorical columns one-hot encoded against a vocabulary derived from the train split itself, never hardcoded, with an explicit `__unknown` bucket for a value the test split has that train did not), `metrics.py` (stdlib-only ROC-AUC — the Mann-Whitney-U tie-averaged rank form, verified against analytic perfect-separation/perfect-reversal/tied cases — plus precision/recall/F1/false-positive-rate; deliberately no numpy/sklearn, so the metric computation is auditable, not a library black box), `harness.py` (`run_benchmark` fits `sm_ml.models.StatisticalModel` — the platform's own always-available detector — on the train split's **benign-only** rows, exactly how `detection-engine` actually uses it in production (ADR-013), then scores the full labeled test split; `BenchmarkRun` records dataset id + both file sha256s, preprocessing version, split sizes, model + params, seed, every metric, and the real environment). New CLI: `python -m sm_ml_training benchmark --dataset nsl-kdd --train <path> --test <path>`. **Real, executed run** against the actual locally-staged `KDDTrain+.txt`/`KDDTest+.txt`: 125,973 train rows (67,343 benign used for the fit), 22,544 test rows (12,833 anomalous) → ROC-AUC 0.639039, precision 0.581191, recall 0.681914, F1 0.627537, false-positive rate 0.649367 — reported exactly as measured, no tuning to improve it. Dataset-availability finding: CICIDS2017/UNSW-NB15/LANL are not locally usable in labeled form (documented, no number claimed for any of them). New `ml/datasets/nsl-kdd/MANIFEST.md`. 26 new unit tests. | 15 (Unit 2) |
| 2026-09-12 | **Real tracing + the remaining ADR-020 metrics + `/health/deps` parity** (Phase 15, Unit 1): no contract changed this unit. New `sm_common.fastapi.TracingMiddleware` opens a real OTel server span per HTTP request (W3C extract/inject); `current_trace_id()`/`remote_context_from_trace_id()` (`sm_common.observability.tracing`) read it and reconstruct a remote parent for a Kafka-consumer span — `None`/no-link, never fabricated, when no real OTel provider is configured (the ubiquitous local-dev/CI case). Wired into all 14 services and both true envelope-origin points (`ingestion-gateway`, `simulation-service`); `sm_common.bus.RecordProcessor` now opens a consumer span per record. Two genuinely-missing ADR-020 metrics added: `sm_db_pool_{size,checked_out,overflow}` (10 Postgres-backed services) and `sm_neo4j_query_duration_seconds` (`graph-service`'s `Graph` client — the only direct Neo4j connection). Model-inference latency/DEGRADED, detection latency, and graph-growth rate were already real and wired under `ml-inference`/`detection-engine`/`graph-service`'s own metrics classes — not duplicated. `sm_false_positive_feedback_total` registered with no producer (no analyst false-positive action exists in this build). `/health/deps` added to the 13 services that lacked it, reusing each service's already-tested readiness computation; two services' extra dependency entries (previously only inside `/readyz`) refactored into a shared `_status()` helper so `/health/deps` is not a narrower view. `deploy/prometheus/prometheus.yml` scrape-target parity added for all 13 previously-unscraped services. 924 unit tests (41 new) + 169 real-infra integration tests green; manually verified against a rebuilt image on the real compose stack. | 15 (Unit 1) |
| 2026-09-12 | **Phase 14 closed** (Unit 4): reports + narrative surfaced through the SOC BFF and the frontend. `sm_contracts.report` gains `ReportDownload` (`report` + presigned `download_url`, moved from a reporting-service-local definition into the shared contract). Migration `0013` widens the `permission.code` CHECK and seeds/grants `reports:read` to all five roles (same tier as `memory:read`). `api-gateway` gains `routes/reports.py`: `POST /api/v1/soc/reports` (`CreateReportRequest` never accepts `requested_by` from the client — the server derives it from the session principal; a compliance-kind report additionally requires the caller hold `lead` or `tenant_admin`, enforced in route code on top of `reports:generate`), `GET /api/v1/soc/reports/{id}`, `GET /api/v1/soc/incidents/{chain_id}/narrative` (gated on the existing `detections:read` tier rather than a new code). `frontend/web/app/(soc)/reports` (builder + session-local library + lookup-by-id with the presigned download link) and `.../story` (chain-id lookup → deterministic beats + one grounded summary), both using a new shared `GroundingTag` component (`.tier-badge` CSS, `synthetic` reusing the Phase 12 "Simulation" amber). `api-gateway` unit tests +10 (BFF proxy, `requested_by` never trusted, compliance-role gate 403/200, narrative 404/200); frontend +6 vitest (`reports`/`story` pages) + 2 `contract.test.ts` fixtures (`Report`, `Narrative`). Real external-infra finding: Docker Hub's `minio/minio` repository now refuses anonymous pulls of the pinned release tag (`pull access denied`) — confirmed as a genuine registry-side change (reproduced locally, and via one CI rerun, not a transient blip) rather than a code defect; fixed by repointing both `docker-compose.yml` and CI's "Start MinIO" step at `quay.io/minio/minio` (MinIO's own mirror, identical image digest). Phase 14 exit report + §23 review in `IMPLEMENTATION_STATE.md`; `REQUIREMENTS_TRACEABILITY` R22 / R33 → IMPLEMENTED (each with an explicit deviation noted, not rounded up). | 14 (close) |
| 2026-09-12 | **Attack storytelling built** (Phase 14, Unit 3; req 33): new `sm_contracts.api.narrative` (`Narrative`, `NarrativeBeat`) — `NarrativeBeat`'s factual fields (`stage`, `detection_ids`, `technique_ids`) mirror `ChainStageModel` exactly and are never touched by an LLM; `Narrative.summary` is the one LLM-composed part, grounded with the same citation-and-retry mechanism `IncidentAnalyst.explain` (Phase 6) uses — every sentence must cite a beat's `stage`, one repair turn, then a deterministic template (`degraded=True`). `Narrative.simulated` + every beat's `tier=GroundingKind.synthetic` when the chain's subject id is simulation-generated (`sm_ml.scenario.is_synthetic_id`) — the contract-level form of Phase 12's "SIMULATION" badge. `services/ai-analyst` gains its first database (`narrative` table, migration `0012`, upserted per `(tenant_id, chain_id)`) and its first cross-service call (`chains_client.py` to `correlation-engine`, copied from `sm_memory_service`'s). `GET /api/v1/incidents/{chain_id}/narrative` — "incident" is an attack chain; this platform has no separate `Incident` entity yet (§3 still PLANNED). 99 JSON Schema files (2 new). 13 new unit tests + 4 new real-Postgres integration tests. Verified end-to-end against the real compose stack, including a simulated chain narrating correctly as `synthetic` throughout. | 14 (Unit 3) |
| 2026-09-11 | **`reporting-service` built** (Phase 14, Unit 2): `services/reporting-service` (port 8013, HTTP-triggered, no Kafka consumer) implements `POST /api/v1/reports` + `GET /api/v1/reports/{id}` against every content dependency `service-catalog.md` names — `detection-engine` via direct Postgres read (no read API of its own; mirrors `api-gateway`'s `SqlSocRepository`), `graph-service`/`mitre-service`/`ai-analyst`/`memory-service` via internal HTTP (`content_client.py`, mirrors `InternalServiceClient`). `ai-analyst`'s grounded narrative only fires for a `detection` subject (`ExplainRequest` has no host/ip/domain/identity variant); a `memory-service` lateral-movement prediction at `confidence == 0.0` is never surfaced as a finding. A content dependency's failure lands its section in `missing_sections` -> `partial`, filtered against the report kind's own seeded `report_template.sections` first. PDF rendering (`reportlab`, this service's own dependency, not `sm_common`'s) + upload via `sm_common.objectstore`; only an object-storage failure produces `failed`. No new contracts this unit — `Report`/`GroundedStatement`/`GroundingKind` (Unit 1) are unchanged; `sm_contracts.api.analyst.Explanation`/`ExplainRequest` and `sm_contracts.api.prediction.Prediction` are consumed as-is. Verified end-to-end against the real compose stack (real PDF uploaded to MinIO, downloaded via its presigned URL). 27 new unit tests + 6 new real-Postgres integration tests. | 14 (Unit 2) |
| 2026-09-11 | **Report + grounding contracts** (Phase 14, Unit 1): new top-level `sm_contracts.report` (mirrors `chains.py`/`memory.py`'s pattern of an entity beside its own topic payload). `GroundingKind` (`evidence` / `inference` / `prediction` / `synthetic` — named to avoid colliding with `threatintel.py`'s unrelated `Provenance` model) is the four-tier distinction Phase 14's grounding requirement demands; `GroundedStatement` (`text` + `tier` + optional `ref`) is the shared building block for a report's findings, recommendations, and timeline points, never a bare string. `Report` carries incident metadata, timeline (`ReportTimelineEntry`), affected assets (`ReportAsset`), detection ids, evidence, chain ids, technique ids, threat score, findings, recommendations, confidence, provenance, and `missing_sections` (populated instead of fabricating content when a dependency is unreachable — `status` is `partial`, never faked). `ReportGeneratedPayload` fills the already-pre-declared `report.generated` topic (`EventType.report_generated` — confirmed still present from an earlier phase's anticipation, same pattern as Phase 13's `campaign.updates`). New `PermissionCode.reports_read` (enum only this unit; the CHECK-widening migration lands with the BFF unit, matching `memory:read`'s Phase 13 precedent). `sm_common.db.report_models` (`ReportTemplateRow`, `ReportRow` — the assembled `Report` body stored whole as JSONB, deliberately not normalized further since a report is a point-in-time snapshot) + migration `0011` (creates `report`/`report_template`, seeds one default template per `ReportKind`). New `sm_common.objectstore` (ADR-019): `ObjectStore` (async `aioboto3`) + `safe_key()` (path-traversal / malicious-filename guard — the only way to build an object key) + `ensure_bucket()` (idempotent, sets default SSE-S3 AES256 encryption). 5 new JSON Schema files (97 total), 11 new unit tests. | 14 (Unit 1) |
| 2026-09-11 | **Phase 13 closed** (Unit 4): threat memory + predictions surfaced through the SOC BFF and the frontend. New permission `memory:read` (migration `0010` — widens the `permission.code` CHECK, seeds and grants it to `platform_operator` / `tenant_admin` / `lead` / `analyst` / `read_only` — this is read-only analytical information, unlike Phase 12's operator-action permissions). `api-gateway` gains `routes/memory.py`: `POST /api/v1/soc/memory/similar`, `GET .../patterns`, `.../fingerprints/{type}/{id}`, `.../campaigns[/{id}]`, and `POST /api/v1/soc/predict/{attack-progression,next-action,lateral-movement,threat-trajectory}` — every route behind `require_permission(memory:read)`, tenant-scoped from the session, CSRF on writes. `frontend/web/app/(soc)/memory` — a campaigns list (with a "predict trajectory" action), an adversary-fingerprint lookup (with a "predict lateral movement" action), a similarity search form, and chain-based predictions (attack progression / next action); every `Prediction` is rendered with its confidence, evidence, and model version — never a bare verdict. `api-gateway` unit tests +10 (BFF proxy, authz, 404s); frontend +3 vitest (`memory` page) + 2 `contract.test.ts` fixtures (`Campaign`/`AdversaryFingerprint`, `Prediction`). Phase 13 exit report + §23 review in `IMPLEMENTATION_STATE.md`; `REQUIREMENTS_TRACEABILITY` R15 / R21 / R37 → IMPLEMENTED (R15 explicitly as deterministic heuristics, not a trained model — the deviation from the original `{predicted_action, probability, horizon, confidence}` sequence-model shape is stated plainly, not rounded up). | 13 (close) |
| 2026-09-11 | **Prediction interfaces** (Phase 13, Unit 3): **no trained predictive model exists in this build.** `sm_ml.predict` (`MODEL_VERSION = "heuristic-v1"`) — `predict_attack_progression` (the kill-chain stage after a chain's furthest-reached stage, confidence from the chain's own `confidence` + `distinct_stage_count`), `predict_next_action` (a technique the subject has used before but not yet in the current chain — grounded in that subject's own history, never a guess about an unobserved technique), `predict_lateral_movement` (the other recorded adversary fingerprint most similar by technique-overlap cosine similarity, not a live graph traversal), `predict_threat_trajectory` (escalating / active / stalling / concluded from a campaign's own status + chain count). Every function returns `confidence=0.0` with a stated reason when the input cannot support a prediction. New `sm_contracts.api.prediction`: `Prediction` (`kind`, `subject_type` — `None` for the campaign-level `threat_trajectory`, which has no single subject — `subject_id`, `prediction`, `confidence`, `evidence`, `features`, `model_version`, `generated_at`) plus one request shape per kind. `memory-service` gains `POST /api/v1/predict/{attack-progression,next-action,lateral-movement,threat-trajectory}` (internal-JWT only), wiring the heuristics to real data via the existing `ChainsClient` (the full chain, since the `attack_chains` topic event carries no technique data) and `MemoryRepository` (a new `list_fingerprints` method supplies lateral-movement candidates). 22 new unit tests (14 heuristics, 8 route). | 13 (Unit 3) |
| 2026-09-11 | **memory-service** (Phase 13, Unit 2): consumes `attack_chains` (group `memory`); the topic event is a thin projection with no technique data, so `ChainsClient` fetches the full chain from `correlation-engine`'s internal read API (`GET /api/v1/chains/{id}`) before learning anything. Upserts a `ThreatMemory` pattern (union of technique ids, `occurrence_count` bumped, never one row per occurrence), matches-or-starts a `Campaign` via pgvector cosine similarity against the tenant's active campaigns (`SM_MEMORY_CAMPAIGN_SIMILARITY_THRESHOLD`, default 0.5; falls back to a bounded Python scan on a DB error), and upserts an `AdversaryFingerprint` — then produces `campaign.updates` (`CampaignUpdatePayload`, a thin projection mirroring `AttackChainPayload`, added to `sm_contracts.memory` alongside its entities). `sm_contracts.memory` moved out of `api/` (where Unit 1 placed it) to sit beside its own topic payload — the same placement `chains.py` uses for `AttackChainModel` + `AttackChainPayload`. `POST /api/v1/memory/similar` (internal-JWT only, tenant-scoped, `SimilarityMatch.exact_fallback` tells the caller which path answered) plus read routes for patterns / fingerprints / campaigns. `RetentionSweeper` — the deletion lifecycle: a campaign ages `active -> dormant -> closed` on inactivity (`SM_MEMORY_DORMANT_AFTER_DAYS` / `SM_MEMORY_CLOSE_AFTER_DAYS`) and patterns / fingerprints / long-closed campaigns are deleted past `SM_MEMORY_RETENTION_DAYS` — mirrors `threat-intel-service`'s expiry sweeper. A real-Postgres integration test (`tests/integration/test_memory_repository_pg.py`, 6 tests) caught a real bug: `sm_common.db.Database`'s sessionmaker runs `autoflush=False` platform-wide, so the sweep's in-memory campaign-status transitions were invisible to the same-transaction `DELETE` that followed, until an explicit `flush()` was added between them. 16 new unit tests (9 route authz/behavior, 5 ingest-handler with fakes, 2 retention-sweeper wrapper). | 13 (Unit 2) |
| 2026-09-11 | **Threat-memory core** (Phase 13, Unit 1): `sm_ml.memory.technique_feature_vector` — a deterministic, L2-normalized, hashed-bag-of-techniques vector (`sha256(technique_id) % 32` buckets); explicitly **not a trained embedding**, no semantic claim beyond "shared techniques land closer together." `cosine_similarity` — the Python exact-match fallback used when pgvector is unavailable. New `sm_common.db.memory_models`: `ThreatMemoryRow` (a behavioral pattern per subject, upserted, unique on tenant+subject+pattern), `CampaignRow` (a set of related attack chains), `AdversaryFingerprintRow` (one evolving fingerprint per subject, unique on tenant+subject) — each carries a `pgvector` `vector(32)` `feature_vector` column with an `hnsw`/`vector_cosine_ops` index (migration `0009`, `CREATE EXTENSION IF NOT EXISTS vector`). New `sm_contracts.api.memory`: `ThreatMemory` / `Campaign` / `AdversaryFingerprint` / `SimilarityMatch` (`MemoryPatternKind` and `CampaignStatus` are closed `Literal` sets) — the raw feature vector is never part of any response, only a similarity score is ever returned, and `SimilarityMatch.exact_fallback` tells the caller which path answered. The Postgres image is now `pgvector/pgvector:pg16` in both `docker-compose.yml` and CI's `integration` job (ADR-006 already specified pgvector; this is the first phase to actually need it). `tests/integration/test_memory_models_pg.py` (6 tests) proves a DB-side pgvector nearest-neighbor query and the Python fallback rank the same two candidates identically, tenant scoping holds, both upsert-uniqueness constraints hold, and each `CHECK` constraint (`subject_type`, `status`) rejects an out-of-vocabulary value at the database layer. `docs/ARCHITECTURE_DECISIONS.md` ADR-011's three-store split (operational graph / knowledge graph / threat memory) is what this table design follows — threat memory duplicates neither the graph nor the detection/chain tables. | 13 (Unit 1) |
| 2026-09-11 | **Phase 12 closed** (Unit 4): digital twin + blast radius surfaced through the SOC BFF and the frontend. `sm_ml.twin.twin_from_synthetic_env(env) -> TwinModel` — reads a deterministic twin directly off the same `SyntheticEnvironment` a scenario runs against (a fixed role-dependency graph: web → app → db/file, workstation → dc, dc trusts every host), so there is no second, independently-maintained asset inventory to drift from it. New contracts `TwinAssetOut` / `TwinRelationOut` / `TwinWeaknessOut` / `TwinSnapshot` / `BlastRadiusRequest` / `BlastRadiusResult`. `services/simulation-service` gains `GET /api/v1/sim/twin?seed=` and `POST /api/v1/sim/twin/blast-radius`. New permissions `simulation:run` / `deception:manage` (migration `0008` — widens the `permission.code` CHECK, seeds both codes, grants them to `platform_operator` / `tenant_admin` / `lead` / `analyst`, deliberately not `read_only`). `api-gateway` gains `routes/simulation.py`: `POST /api/v1/soc/simulation/run`, `GET .../twin`, `POST .../blast-radius`, and the deception proxy (`POST/GET/DELETE /api/v1/soc/deception/decoys...`) — every route behind `require_permission`, tenant-scoped from the session, CSRF on writes; a downstream `422` (isolation refusal, `feed_pipeline` with no bus) is now re-raised as `ValidationFailed` instead of a misleading `DependencyUnavailable` (503) — the dependency understood and rejected the request, that is not an outage. `frontend/web/app/(soc)/simulation` (run form + twin table + per-asset blast-radius) and `.../deception` (register / list / teardown / interactions), both badged "SIMULATION"; nav gated on the new permissions. `sm_ml` unit tests +7 (`twin_from_synthetic_env`); `simulation-service` unit tests +5 (twin route); `api-gateway` unit tests +12 (BFF proxy, authz, 422-not-503); frontend +9 vitest (`simulation`/`deception` pages) + 3 `contract.test.ts` fixtures; `tests/integration/test_migrations_pg.py` updated for head `0008` / 16 permissions. Phase 12 exit report + §23 review in `IMPLEMENTATION_STATE.md`; `REQUIREMENTS_TRACEABILITY` R16 / R17 / R35 → IMPLEMENTED, R26 → FOUNDATION IMPLEMENTED (no demo-tenant / guided-walkthrough layer built — stated plainly, not claimed done). | 12 (close) |
| 2026-09-11 | **Simulation service + deception registry** (Phase 12, Unit 3): new `sm_contracts.api.simulation` — `RunScenarioRequest` (name, kind, seed, target_host, target_identity, intensity 1-5, `feed_pipeline`), `ScenarioRunResult` (`synthetic=True` always, `scenario_id`, `events: list[SimEventOut]`, `fed_to_pipeline`, `fed_event_count`), `RegisterDecoyRequest` / `Decoy` (`kind` ∈ {honeypot_host, honeytoken, decoy_credential}; `network_boundary` ∈ {isolated, dmz-isolated} — **`'production'` is not a legal value**, so a decoy can never be recorded as attached to production; `status` ∈ {active, torn_down}; no credential field), `DecoyInteractionIn` / `DecoyInteraction` (attacker-supplied `source`/`detail`, captured for display only, never trusted or executed). New service `services/simulation-service` (port 8011): `POST /api/v1/sim/scenarios/run` builds a fresh `sm_ml.scenario` synthetic environment from the request's own seed and runs one of the four templates against it — `ScenarioIsolationError` → 422, never a real system; `feed_pipeline: true` additionally produces every mappable event onto `telemetry.raw` (`source.type = "simulation"`, `pipeline.py`) so a drill exercises the real normalization → detection → correlation → graph pipeline, clearly labelled at every hop; refused (422, not silently dropped) when the event bus is disabled. `POST/GET/DELETE /api/v1/deception/decoys...` — the decoy registry (`DecoyRepository`, Postgres tables `decoy` / `decoy_interaction`, migration `0007`; `network_boundary` is CHECK-constrained at the database level too, so the invariant holds even if a caller bypasses the API schema); teardown is idempotent; a torn-down decoy captures no further interactions; interaction history survives teardown for audit. 23 unit tests (route authz, deterministic run, isolation refusal, `feed_pipeline` without a bus, decoy lifecycle, interaction capture on active vs. torn-down) + 4 real-Postgres integration tests (`tests/integration/test_simulation_pg.py`: tenant isolation, idempotent teardown keeps history, torn-down capture is refused, the `network_boundary` CHECK rejects `'production'` at the database level). | 12 (Unit 3) |
| 2026-09-11 | **Synthetic attack-scenario engine** (Phase 12, Unit 2): `sm_ml.scenario` — `build_synthetic_env(seed)` (deterministic; every entity id `sim-`-prefixed, `synthetic=True`; `is_synthetic_id` is the check every scenario target passes through — **a scenario may never touch a real or unknown entity**). `ScenarioSpec` (Pydantic, frozen, `extra=forbid`: `kind` ∈ {apt, ransomware, insider, brute_force}, `seed`, `target_host`, `target_identity`, `intensity` 1-5). `validate_spec(spec, env)` raises `ScenarioIsolationError` unless every target is a synthetic id present in `env` — checked before any event is generated. `run_scenario(spec, env)` — a seeded-RNG deterministic ordered `SimEvent` list per kind (apt: recon → initial_access → lateral_movement → collection → exfiltration; brute_force: an `auth_failed` burst then one `auth_success`; ransomware: `auth_success` → discovery `process_exec` → `file_access` write bursts; insider: an off-hours `auth_success` from an unusual host → bulk `file_access`); every event carries `simulated=True` + its `scenario_id`; `intensity` scales event volume. `replay_run(run, from_step=, to_step=)` — a deterministic, read-only slice; an inverted window raises. No contract model yet — lands with the service in Unit 3. 17 unit tests (deterministic env + run, isolation rejections, per-kind event-kind coverage, intensity scaling, ordering, replay slicing + inverted-window rejection). | 12 (Unit 2) |
| 2026-09-10 | **Security digital twin** (Phase 12, Unit 1): `sm_ml.twin` — `TwinModel` (`TwinAsset` + `TwinRelation` + `TwinWeakness`; `build_twin` validates endpoints / dup ids / weakness refs, freezes, and sorts → deterministic and standard-library). `attack_paths(twin, sources=, targets=, max_depth=)` (bounded simple paths, feasibility = product of relation weights, ordered), `blast_radius(twin, seeds=, max_hops=, min_weight=)` → `BlastRadiusReport` (reached set + per-hop distance + critical-assets-reached + a criticality-weighted `score` ∈ [0,1] + amplifying weaknesses), `stress_test(twin, ..., controls=[DefensiveControl])` → `StressReport` (paths before/after, paths broken, residual risk, most-valuable control). No contract model yet — the `sm_contracts` shapes land with the BFF in Unit 4. **Scenario execution and blast-radius analysis run against this model, never real systems.** 11 unit tests. | 12 (Unit 1) |
| 2026-09-10 | **Phase 11 CI-verified** — final run `34448406595`, all five jobs (unit runs `34446018571` / `34447606633`). | 11 (close) |
| 2026-09-10 | **Threat-hunting panel** (Phase 11, Unit 3): `frontend/web/app/(soc)/hunt` — an "Ask" natural-language mode (`{query}`) and a "Quick query" structured form (`{plan}`, no LLM), both rendering the **compiled `QueryPlan`** JSON so the analyst sees exactly what structured query ran, plus the grounded explanation, a rows table, and a "Pivot" action (runs `list_related` on a result row's entity, mapping the graph node label back to a hunt entity type). Nav entry gated on `hunt:query`. `api.hunt(body, csrfToken)` typed helper; `contract.test.ts` gains a `SocHuntResponse` fixture. `frontend/web` `npm run build` OK (15 routes), 41 vitest tests. `REQUIREMENTS_TRACEABILITY` R18 / R32 → IMPLEMENTED (with the no-live-provider / no-full-text-search / no-saved-queries deviations spelled out). | 11 (close) |
| 2026-09-10 | **NL hunting + orchestration** (Phase 11, Unit 2): `ai-analyst` `HuntPlanner` (`POST /api/v1/hunt/plan`) — the LLM produces **only** a `QueryPlan` (parsed into the closed `sm_contracts.QueryPlan` model — never used as a query) or `{"unsupported": true, "reason": ...}`; non-JSON output, an invalid intent, or no LLM → `PlanResponse(supported=false)`. `explain_hunt` + `POST /api/v1/hunt/explain` — a grounded one-paragraph summary citing the plan; a deterministic baseline without an LLM. `api-gateway` `POST /api/v1/soc/hunt` (`require_permission(hunt:query)` + CSRF; tenant from the session `Principal`, never a body field) — `body.plan` runs directly (no LLM); `body.query` goes `ai-analyst /hunt/plan` (unsupported → `SocHuntResponse(supported=false)`, **not executed**) → `graph-service /graph/hunt` → `/hunt/explain` (best-effort). The natural-language text is never sent to `graph-service`. Every hunt is recorded to `hunt_query` (`sm_common.db.HuntQueryRow` + migration `0006`, append-only, tenant-scoped — stores mode + NL text + resolved intent + row_count + `cypher_fingerprint`, never the result rows). New: `SocHuntRequest` / `SocHuntResponse` / `HuntExplainRequest`. 28 tests (planner: no-LLM / valid-plan / model-unsupported / non-JSON / invalid-intent / injection-in-NL / row-cap; `/soc/hunt`: authz + CSRF, quick vs NL, unplannable → not executed, 503, no-tenant-field). | 11 (Unit 2) |
| 2026-09-10 | **Hunt query plan + deterministic compiler** (Phase 11, Unit 1): `sm_contracts.api.hunt` — `QueryPlan` (**closed schema**: `HuntIntent` ∈ {find_entity, list_related, path_between, detections_for, chains_for, indicator_sightings, technique_usage}, typed `EntitySelector`s, a `rel_types` allow-list, `QueryLimits`), `NlHuntRequest`, `PlanResponse` (`supported` + optional `plan` + `unsupported_reason`), `HuntResult` (rows + `cypher_fingerprint` + `explanation`). `graph-service` `hunt.py` — `validate_plan` (capability-set enforcement), `compile_plan` (intent → one constant parameterized Cypher template; label/reltype/int-depth are the only interpolations, all allow-listed; every value is a `$` param; `$tenant` from the token, no plan field for it), `HuntRunner`. `POST /api/v1/graph/hunt` (internal JWT; a plan outside the set → 422). `SM_HUNT_MAX_ROWS` (200) / `SM_HUNT_MAX_DEPTH` (3), applied on top of the plan's own limits. See §5. Real-Neo4j `test_hunt_neo4j.py` (tenant-scoped, cross-tenant isolation, hallucinated entity → empty). 17 unit tests. | 11 (Unit 1) |
| 2026-09-10 | **Phase 10 CI-verified** — final run `34432159191`, all five jobs (unit runs `34429226626` / `34429715242` / `34430968254`). | 10 (close) |
| 2026-09-10 | **Phase 10 closed** (Unit 4): multi-agent defense. `sm_ai.agents` — `AgentSpec` (name + fixed system prompt + tool **allow-list**), `run_agent` under `AgentLimits` (`max_steps` / `max_tool_calls` / `wall_clock_s` / cumulative-token `RunBudget`) + a cancellation `Event`. `DETECTION_AGENT` / `THREAT_INTEL_AGENT` / `RESPONSE_AGENT`. An agent **cannot spawn another agent**, **cannot execute** anything, and holds **no standing permissions**; a tool outside its allow-list or unauthorised is refused mid-run without stopping the run; a tool exception is a tool result, not a crash. `sm_ai.action_gate` — `suggest_only` → `denied`; `allowed` needs `auto` + no approval requirement + production + a signed policy + a reversible action, so with the shipped `SM_RESPONSE_MODE=suggest_only` + `SM_RESPONSE_APPROVAL_REQUIRED=true` an agent proposal is **never** `allowed` (R31 / §7.3 boundary). `sm_contracts.api.agent` — `AgentRunRequest` / `AgentRunResult` (findings + `proposed_actions` with a per-action `decision`) / `AgentFinding` / `ProposedActionOut`. `services/ai-analyst` `POST /api/v1/agents/run` (internal JWT; no live LLM → `status="failed"`, never a 500). `FunctionTool` made non-generic (Protocol invariance). See §7.6. `REQUIREMENTS_TRACEABILITY` R29 / R30 → IMPLEMENTED, R31 → FOUNDATION IMPLEMENTED. 31 tests (allow-list boundary, unauthorised tool refused mid-run, step / tool-call / wall-clock / budget limits, cancellation, `action_gate` truth table, "suggestion ≠ action", route authz + no-LLM). | 10 (close) |
| 2026-09-10 | **AI analyst service** (Phase 10, Unit 3): `services/ai-analyst` (module `sm_ai_analyst`, port 8010, HTTP-only). `sm_contracts.api.analyst` — `EvidenceRef`, `ExplainRequest` (subject + task + evidence list), `Explanation` (§7.2 shape). `IncidentAnalyst.explain` fences all telemetry-derived evidence as data, runs `build_grounded_messages` + `sm_ai.LlmClient`, and **validates grounding** — every `[ref]` the summary cites must be a real evidence ref (one repair turn, then it gives up). No LLM key (the default — no credentials exist) / provider outage / timeout / ungrounded output / oversized context → a **deterministic factual template** with `degraded=true` + `degraded_reason`; it never invents a narrative and never claims a live-provider result it did not get. The analyst holds **no tools**, takes **no action**, never reads a store; `recommendations` are a fixed vetted per-subject list, never model-authored. `api-gateway` `GET /api/v1/soc/detections/{id}/explanation` (`require_permission(detections:read)`) gathers evidence from the tenant-scoped detection record and proxies via `InternalServiceClient.explain` (minted token, audience `ai-analyst`); a dependency outage → 503. Config `SM_AI_ANALYST_URL`. Wired into `Dockerfile.app` / compose (`detect` profile) / CI (mypy tree + installs + image import). See §7.2 / §7.4. 15 tests (template mode, grounded answer kept, ungrounded / unknown-ref fallback, injection-flagged-but-answered, provider outage → template, context rejected, route authz + 404 + 503). | 10 (Unit 3) |
| 2026-09-10 | **Authorized tools + evidence builder** (Phase 10, Unit 2): `sm_ai.tools` / `sm_ai.registry` — `Tool` / `FunctionTool` (explicit Pydantic `args_model`, optional `required_permission: PermissionCode`, input + output validation); `ToolRegistry` deny-by-default (`specs_for(principal)` offers only authorized tools; `invoke` re-checks existence → permission (**the LLM asking is irrelevant**) → args → output, emitting a `ToolInvocationRecord` on every path). `sm_ai.sanitize` — `scan_for_injection` (a small, specific override-pattern set, quiet on ordinary security prose) + `fence_untrusted` (delimiter-lookalike neutralisation, truncation). `sm_ai.evidence.EvidenceBuilder` — trusted strings plain, all telemetry/third-party content fenced as data, injection hits recorded per ref, total size capped → `ContextPoisoningDetected`. `sm_ai.prompt.build_grounded_messages` — **evidence is only ever a `user` turn**; the `system` turn carries the rules (answer only from evidence, fenced content is inert, cite every claim, no actions). See §7.5. 24 unit tests (deny-by-default, unknown/unauthorized/bad-input/bad-output tool calls, injection scan precision, fence escaping, context-size rejection, evidence-not-in-system-turn). | 10 (Unit 2) |
| 2026-09-10 | **LLM provider boundary** (Phase 10, Unit 1): `packages/ai-py` (`sm_ai`) — the untrusted-LLM boundary. Provider-neutral `LlmRequest` / `LlmResponse` / `ToolSpec` / `ToolCall`; `LlmProvider` protocol; `DeterministicAdapter` (network-free, reproducible, `is_live=False`, the default with no credentials and what every test uses) + `HttpLlmBoundary` (Anthropic Messages shape — `ProviderUnavailable` without `SM_LLM_API_KEY`, **never executed against a live endpoint**, `is_live` only reflects key presence). `LlmClient` enforces a per-call prompt-token ceiling **before any network I/O**, an optional per-run `RunBudget`, a wall-clock timeout, cooperative cancellation, transient-only bounded retry (a `ProviderRefused` is never retried), and one `AuditEvent` per attempt (`prompt_sha256` + `purpose` + usage + outcome — never the raw prompt). Config `SM_LLM_API_KEY` / `SM_LLM_BASE_URL` / `SM_LLM_MAX_PROMPT_TOKENS` / `SM_LLM_MAX_COMPLETION_TOKENS` / `SM_LLM_MAX_RETRIES` + `SM_AGENT_MAX_STEPS` / `SM_AGENT_MAX_TOOL_CALLS` / `SM_AGENT_WALL_CLOCK_TIMEOUT_S` / `SM_AGENT_MAX_LLM_TOKENS_PER_RUN`. CI: `ai-py` added to the `static` mypy trees + all three install blocks. See §7.4. 21 unit tests (determinism, budget rejection before call, retry-on-transient / no-retry-on-refused, timeout, provider outage, boundary inert without a key, audit emission). | 10 (Unit 1) |
| 2026-09-10 | **Phase 9 closed** (Unit 4): attack graph + realtime + polish. `sm_contracts.api.graph` — `GraphNode` / `GraphEdge` / `GraphNeighborhood` / `GraphPath` promoted from the `graph-service` draft schemas so the browser consumes generated types; `properties` is display-only and documented as never used for an auth/routing decision. `api-gateway` `GET /api/v1/soc/graph/{neighbors,paths}` now `response_model` these (a graph-service drift → the BFF's own tests fail, not a silently-wrong UI); a non-object upstream response → 503. `frontend/web`: `graph/page.tsx` is a Cytoscape explorer (lazy-loaded client-only, `aria-hidden` canvas) with a node/edge **detail panel** and an accessible node/edge **list fallback** that is the real representation for assistive tech + keyboard; a `truncated` neighbourhood is flagged. `useResource` gains an optional `refreshMs` poll + `updatedAt`; `LiveBadge` ("Updated Ns ago · auto-refresh Ns") on the dashboard + alerts list — an honest poll, a test asserts the text says neither "streaming" nor "live". `prefers-reduced-motion` disables animation. `cytoscape` + `@types/cytoscape` added to `frontend/web`. Tests: `AttackGraph` (cytoscape mocked), `graph/page`, `LiveBadge` — 37 vitest total. Phase 9 exit report + §23 review in `IMPLEMENTATION_STATE.md`; `REQUIREMENTS_TRACEABILITY` R13 / R25 → IMPLEMENTED (P9 core; WebSocket realtime, `notification-service`, cinematic replay, Playwright/axe-in-CI deliberately deferred). | 9 (close) |
| 2026-09-10 | **SOC views** (Phase 9, Unit 3): `frontend/web` renders real, typed views for every read surface the BFF exposes — dashboard, alerts list + `incidents/[id]` (which also fetches the triggering detection: rule id, evidence, ATT&CK techniques), attack-chain list + `chains/[id]` (kill-chain stage table with per-stage detection count + max severity), MITRE ATT&CK heatmap, risk heatmap, entity explorer + `entities/[id]` timeline, threat-intel indicators. A single `DataView<T>` primitive renders the loading / error / empty / ready branches so no view can forget one; severity is colour + text + shape everywhere. **No backend shape is re-declared** — every type is imported from `@sentinelmesh/contracts`, and optional generated array fields are guarded (`(x ?? [])`) under `noUncheckedIndexedAccess`. **No attack activity is fabricated** — empty states name the missing upstream (e.g. "Mappings appear once mitre-service has processed detections against an imported ATT&CK catalog"). `src/lib/contract.test.ts` compile-checks fixture responses against the generated types, so a regenerated contract that the fixture no longer satisfies fails the build. The CI `frontend` job's contract-drift check switched from `git diff --exit-status` (rejected by git 2.55) to `git diff --quiet`. `npm run build` OK (14 routes); 27 frontend unit tests. | 9 (Unit 3) |
| 2026-09-10 | **frontend/web scaffold** (Phase 9, Unit 2): `packages/contracts-ts` now emits a **single** `src/index.ts` from a combined `$defs` schema (`--unreachableDefinitions`), with a real `tsconfig.json` + `typecheck` script — the generated TS types are committed and the frontend imports `@sentinelmesh/contracts`, never re-declaring a backend shape. `jsonschema.py` `ref_template` fixed to `#/$defs/{model}` (the old `#/definitions/` never resolved). `frontend/web` — Next.js 15 App Router + TS, minimal deps. Typed `apiFetch` client (`credentials: "include"`, CSRF header on mutations, `ApiError.kind` maps status → a UI state; no token in JS). `AuthProvider` hydrates `/api/v1/auth/me` — `hasPermission` gates **display only**, never authorization. `middleware.ts` is a redirect-only route guard. `AppShell` (tenant-aware nav filtered by permission), `Loading` / `EmptyState` / `ErrorState` primitives, `Severity` (colour + text + shape, WCAG 1.4.1), a `Placeholder` for not-yet-wired views (honest empty state, never fabricated activity). Dashboard + alerts list are real; the rest are placeholders for Unit 3. CSP + security headers in `next.config.mjs`; `react/no-danger` is an error. New CI `frontend` job: contracts `npm ci` + `gen_contracts.py` + `git diff --exit-status` (types current) + contracts typecheck + `frontend/web` `npm ci` / lint / vitest / `next build`. 19 frontend unit tests. | 9 (Unit 2) |
| 2026-09-10 | **SOC read API** (Phase 9, Unit 1): `api-gateway` becomes the browser-facing BFF. `sm_contracts.api.soc` — `SocSummary` (real per-tenant counters — never a fabricated figure), `RiskSubject`, `MitreHeatmap` / `MitreHeatmapCell`, `TimelineEntry` / `TimelineResponse`; `CursorPage[Detection|SecurityAlert|AttackChainModel|ThreatScore]` exported for the generated TS client. `services/api-gateway` routes `GET /api/v1/soc/*` — `summary`, `detections[/{id}]`, `alerts[/{id}]`, `risk`, `mitre/heatmap`, `timeline/{subject_id}` read straight from Postgres (`SqlSocRepository`, keyset-paged on `created_at`, `WHERE tenant_id = :principal_tenant` — never a query field); `chains[/{id}]`, `graph/{neighbors,paths,intel}`, `ti/indicators` proxy `correlation-engine` / `graph-service` / `threat-intel-service` via `InternalServiceClient` (a per-call service token scoped to the **caller's** tenant, so a browser cannot widen scope). Every endpoint is `require_permission(detections:read)` or `hunt:query` (deny-by-default, metered + audited); a dependency outage → HTTP 503, never a 500 or a fabricated result. Config `SM_GRAPH_SERVICE_URL`. `SocRepository` Protocol so route tests substitute a fake. | 9 (Unit 1) |
| 2026-09-10 | **Phase 8 closed** (Unit 4): graph-model serving + a live intel endpoint. `ml-inference` gains `GraphModelHost` + `POST /api/v1/infer/graph/{model}` (request = nodes + edges + `graph_feature_schema_version`; response = per-node scores) — the `structural` detector is a builtin (always available, no artifact), a GNN name → HTTP 503 `MODEL_UNAVAILABLE` when its artifact or `torch` is missing, a malformed graph → 422 (never a 500) — plus `GET /api/v1/graph/models`; `/readyz` reports the graph catalog. `graph-service` gains `GET /api/v1/graph/intel?label=&key=&depth=` — runs `StructuralGraphAnomaly` + `LabelPropagationClusterer` + `SuspiciousSubgraphHeuristic` over a bounded, tenant-scoped neighbourhood (`GraphIntelResponse`: node anomalies, threat clusters, a subgraph likelihood in `[0,1]`); `sm-ml` added as a `graph-service` dependency. `StructuralGraphAnomaly.from_dict` + the registry now round-trip a calibrated `structural_zscore` artifact. Real-Neo4j integration (`test_graph_intel_neo4j.py`). Phase 8 exit report + §23 in `IMPLEMENTATION_STATE.md`; `REQUIREMENTS_TRACEABILITY` R11 / R12 → IMPLEMENTED (library; **no benchmark verified**), R15 → FOUNDATION IMPLEMENTED. | 8 (close) |
| 2026-09-10 | **ml-training pipeline** (Phase 8, Unit 3): `services/ml-training` (module `sm_ml_training`, offline CLI `sm-ml-train`) — the reproducible `dataset → preprocessing → graph construction → feature generation → training → validation → checkpoint → model version → inference → evaluation` pipeline. `TrainingConfig` (pydantic, frozen) with `config_hash()` (a stable digest — two runs with the same config + dataset write byte-identical `model.json`) and `model_version()` (`0.1.0+<hash12>`). `synthetic_fixture_dataset(seed)` — a deterministic labelled toy graph (one injected anomalous hub per sample), **a plumbing check, never a benchmark**; `load_dataset(path)` for a real JSON-lines benchmark carrying an id + sha256 (no dataset ships, ADR-024). `model_kind = structural` runs fully offline — training **calibrates the anomaly z-threshold** against the labelled train split (an honest supervised hyper-parameter fit); `graphsage` / `gat` need `torch` (`sm-ml[gnn]`) and raise `PipelineSkipped` with no artifact when it is absent. `ModelMetadata` records seed, `sm-ml` / torch versions, dataset id + sha256, git commit, config hash, and an `EvaluationReport` whose `headline_metrics` is `NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION` and `benchmark_verified` is `false` for a fixture run (`val_metrics` are present but explicitly labelled a plumbing check). `write_artifact` writes `<dir>/<name>/<version>/{model.json, metadata.json, stage_log.txt}` in the `GraphModelRegistry` layout; the registry now also loads a `structural_zscore` artifact (calibrated threshold) as a `StructuralGraphAnomaly`. CI: `ml-training` added to the `static` mypy trees + all three install blocks (not the image — it is a dev-time tool). | 8 (Unit 3) |
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
