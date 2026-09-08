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

All payload models are **DRAFT** except `user.event` (Phase 1) and the envelope
itself.

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

## 5. Graph contract (DRAFT — Phase 2/3)

- Node labels, key properties, relationship types, and invariants:
  `docs/architecture/data-model.md`.
- Write path: only via `graph.commands` Kafka topic → `graph-service`. Command
  schema `GraphCommandPayload`: `{ command_id, op: MERGE_NODE|MERGE_EDGE|
  SET_PROPS|PRUNE, label/type, key, props, tenant_id, observed_at }`. Idempotent
  by `command_id` + MERGE semantics.
- Read path: `graph-service` query API. Parameterized only. Every query
  tenant-scoped, depth-bounded (`max_depth`, default 4, hard cap 8), row-capped,
  time-limited. No caller supplies raw Cypher.

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
| 2026-09-08 | Initial contract set authored (Phase 0). API conventions, error contract, envelope, entity list, ownership, graph/ML/AI contract skeletons. | 0 |
| 2026-09-08 | Phase-1 auth/admin API surface **implemented** in `services/api-gateway` and its contracts promoted DRAFT → **STABLE**: API conventions, the canonical error contract, the foundation endpoint set (§1.2), and the `Tenant`/`User`/`Role`/`Permission`/`UserRole`/`RolePermission`/`Sensor`/`AuditRecord` entity contracts. Cursor pagination, CSRF header (`X-CSRF-Token`) and the session cookie names are part of the stable surface. | 1 (Unit 4) |
| 2026-09-08 | `packages/contracts-py` implements the canonical `EventEnvelope`, the `ErrorResponse` contract (`HTTP_STATUS_BY_CODE`), Phase-1 entity DTOs (`Tenant`, `User`, `Role`, `Permission`, `RolePermission`, `UserRoleGrant`, `Sensor`, `AuditRecord`), Phase-1 API models, and shared enums. JSON Schema generated to `packages/contracts-ts/schemas/` via `scripts/gen_contracts.py`. Status of these contracts: **STABLE target** — promoted to STABLE when the Phase-1 endpoints that use them ship. `identity_link` ownership corrected to `normalization-engine` (Phase 2) — see `architecture/consistency-review.md`. | 0 (close) |
