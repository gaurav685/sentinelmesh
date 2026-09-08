# System overview, boundaries, and flows

## 1. System boundary

**Inside SentinelMesh:** ingestion → normalization → event bus → stream
processing → graph → detection/scoring → threat intel / MITRE → memory → AI
analyst / agents → API edge → frontend; plus ML training, simulation, deception,
reporting, observability, deployment.

**Outside SentinelMesh (external systems):**

| External | Direction | Trust |
|---|---|---|
| Customer telemetry sensors / collectors | inbound | **untrusted** — authenticated per sensor, payloads validated, rate/size limited |
| Identity Provider (OIDC/SSO) | inbound auth | trusted for identity assertions only (signature-verified) |
| External threat-intelligence providers | outbound (adapter) | **untrusted responses** — schema-validated, timeouts, failure-tolerant |
| LLM providers (Anthropic/OpenAI/local) | outbound (adapter) | **untrusted responses** — treated as data, tool calls allow-listed, audited |
| Geo-IP database (MaxMind) | local file | trusted (offline data) |
| Object store (S3/MinIO) | outbound | trusted infra, per-tenant prefixing |
| Response-action targets (EDR, firewall, SOAR) | outbound (adapter) | privileged — behind policy + approval + feature flag, default off |
| Kubernetes / cloud control plane | deploy-time | operator-trusted |

## 2. Trust boundaries

```
[ sensors ]══(TB-1)══>[ ingestion-gateway ]──>[ Kafka: telemetry.raw ]
                                                      │
                                              [ normalization-engine ]──(TB-4 outbound)──>[ TI providers ]
                                                      │
                                          [ Kafka: events.canonical ]
                                           │           │            │
                                  [ stream-processor ] │      [ graph-service ]──>[ Neo4j ]
                                           │           │            │
                                   [ Kafka: graph.commands / detections / attack_chains ]
                                           │
                                  [ detection-engine ]──>[ ml-inference ]──>[ model artifacts (S3) ]
                                           │
[ browser ]══(TB-2)══>[ api-gateway ]<────┤ read models (Postgres)
[ browser ]══(TB-2)══>[ notification-service ]<──[ Redis fan-out ]
                          │
                   (TB-3) │ internal service mesh (mTLS + internal JWT)
                          ▼
        [ ai-analyst-service ]──(TB-4)──>[ LLM providers ]
        [ agent-orchestrator ]──(TB-5)──>[ response targets ]  (policy-gated, default off)
        [ deception-service ]  (TB-6: network-isolated segment)
        [ simulation-service ] (TB-7: isolated, synthetic only)
```

| Boundary | Between | Controls |
|---|---|---|
| TB-1 | sensors ↔ ingestion-gateway | per-sensor credential, mTLS (prod), payload schema validation, `SM_HTTP_MAX_BODY_BYTES`, rate limit (fail-closed), tenant bound to sensor identity |
| TB-2 | browser ↔ api-gateway / notification-service | OIDC login, httpOnly Secure SameSite session cookie, CSRF token, restrictive CORS (`SM_CORS_ALLOWED_ORIGINS`, no wildcard in prod), CSP, per-user rate limit |
| TB-3 | service ↔ service (internal) | private network, mTLS (prod), short-lived audience-scoped internal JWT, deny-by-default network policies |
| TB-4 | services ↔ LLM / TI providers | outbound allow-list, egress proxy, timeouts, retries with backoff, response schema validation, **responses are data not instructions**, SSRF guard (no user-controlled URLs), token accounting, audit |
| TB-5 | agent-orchestrator ↔ response targets | policy document + authorization + approval + blast-radius + rollback + audit; `auto` mode gated to production + signed policy |
| TB-6 | deception segment | isolated network, no route to production data planes, one-way telemetry export |
| TB-7 | simulation | isolated; only synthetic deterministic data; results clearly labeled `SIMULATION`; cannot emit `response.actions` |

## 3. Security boundaries (summary — full detail in `security-model.md`)

- **Identity → Tenant → Role → Permission → Resource** established server-side on
  every request. Client-provided identity/tenant/role/permission/ownership is
  never trusted.
- Every tenant-scoped datastore access carries an injected tenant predicate.
- The frontend has **zero** direct access to Postgres, Neo4j, Kafka, Redis, or
  provider APIs.
- LLM-generated content never becomes a privileged action or an executed query
  without deterministic validation (ADR-015) and, for actions, policy+approval
  (ADR-022).

## 4. Actors

| Actor | Description | Auth |
|---|---|---|
| **Tenant** | An isolated customer organization. Root of all data scoping. | n/a (data attribute) |
| **SOC Analyst** | Investigates alerts, hunts, runs simulations/demos. | OIDC user, role `analyst` |
| **SOC Lead / Approver** | Approves response actions, manages investigations. | OIDC user, role `lead` |
| **Tenant Admin** | Manages users/roles within one tenant. | OIDC user, role `tenant_admin` |
| **Platform Operator** | Runs SentinelMesh infra (cross-tenant, break-glass, audited). | OIDC user, role `platform_operator` (separate IdP group) |
| **Sensor / Collector** | Machine identity emitting telemetry for exactly one tenant. | per-sensor credential |
| **Service principal** | Internal service identity. | internal JWT |
| **AI Agent** | Non-human automated actor (detection/TI/response agent). Acts under a constrained service principal + task-scoped tool allow-list. | internal JWT + agent policy |

## 5. Core synchronous flows

1. **Login:** browser → `api-gateway` → OIDC auth-code → session cookie →
   `GET /api/v1/me` returns identity + tenant + effective permissions.
2. **Protected read (e.g. list detections):** browser → `api-gateway`
   (authn + authz + tenant scope + pagination validate) → Postgres read model →
   typed response (never ORM object).
3. **Graph query / hunt:** browser → `api-gateway` → `graph-service`
   (parameterized, depth-bounded, tenant-scoped Cypher, read-only role) → result.
4. **NL hunt (req 32):** browser → `api-gateway` → `ai-analyst-service`
   (LLM → `QueryPlan`) → validate + authz → `graph-service` deterministic query →
   result + grounded explanation.

## 6. Core asynchronous flows

1. **Telemetry:** sensor → `ingestion-gateway` → `telemetry.raw` →
   `normalization-engine` (validate/normalize/enrich) → `events.canonical`.
2. **Graph build:** `events.canonical` → `stream-processor` +
   `graph-service` → `graph.commands` → `graph-service` applies to Neo4j →
   Redis fan-out → `notification-service` → browser live update.
3. **Detection:** `events.canonical` + Flink-derived features →
   `detection-engine` → `ml-inference` → composite score → `detections` /
   `attack_chains` → projected to Postgres read model + pushed to analyst.
4. **Attack chain / lateral movement / temporal:** `stream-processor` keyed
   state over `events.canonical` (event-time windows) → derived events.
5. **Response (guarded):** `detections` → `agent-orchestrator` → policy/approval
   → `response.actions` (adapter) → audit. Default `suggest_only`.

## 7. Component classification (all 38 requirements preserved)

| Class | Requirements |
|---|---|
| **Foundation** | 18(config/deploy parts), 20(bus), 23(observability), 38(deployment), plus Phase-1 auth/tenant/RBAC platform |
| **Core runtime** | 1, 2, 3, 4, 5, 6, 8, 9, 10, 19 |
| **Advanced intelligence** | 7, 11, 12, 14, 15, 16, 17, 21, 29, 32, 36, 37 |
| **Enterprise** | 22, 24, 30, 31, 34, 35, 38 |
| **Presentation / content** | 13, 25, 26, 33, 27, 28, 18(UI) |

Classification governs **phase ordering only** — no requirement is dropped.
