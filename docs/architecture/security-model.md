# Security model

Constitution §§5, 6, 13 are binding. This document is the reference; Phase 1
implements the foundation (auth, tenant isolation, RBAC, audit, HTTP hardening).

## 1. Authorization chain (every request)

```
credential  →  Identity (verified)  →  Tenant (from identity, server-side)
            →  Roles (from user_role, server-side)  →  Permissions (from role_permission)
            →  (permission, resource-scope) check  →  tenant-scoped data access
```

- **Deny-by-default.** A route with no declared permission is unreachable
  (rejected at the router). A permission not granted = 403.
- **Never trusted from the client:** identity, `tenant_id`, roles, permissions,
  resource ownership, `is_admin`-style flags. All resolved server-side from the
  session/token + database.
- **Role escalation prevention:** roles come only from `user_role`; there is no
  request field that can add a role or permission. Granting a role requires
  `roles:grant` permission and is audited.

## 2. Identity & tokens

| Context | Mechanism |
|---|---|
| Browser ↔ api-gateway | OIDC auth-code flow at the gateway → server-side session; **httpOnly, Secure, SameSite=Lax** session cookie (id only); session record in Redis (`sm:session:<sid>`) with absolute + idle expiry; CSRF token (double-submit) for state-changing requests |
| api-gateway ↔ internal services | short-lived internal JWT (≤ `SM_INTERNAL_JWT_TTL_SECONDS`), HS256/RS256 with `SM_INTERNAL_JWT_SIGNING_KEY`, claims: `sub`, `tenant_id`, `roles`, `perm_hash`, `aud=<target service>`, `exp`; verified on every internal call |
| Sensor ↔ ingestion-gateway | per-sensor API key (Argon2id-hashed at rest) → mTLS client cert in production; sensor bound to exactly one `tenant_id` |
| Service ↔ LLM / TI providers | provider API keys from secret store; egress via allow-listed proxy |

Passwords (local fallback users only): **Argon2id** (`argon2-cffi`), per-hash
salt, tuned params, pepper optional via secret. Never logged, never returned,
redacted in errors.

## 3. Brute-force / abuse protection

- Failed login increments `user.failed_login_count`; threshold (config, default
  10) sets `user.locked_until` (exponential). Lockout is per `(tenant, email)`
  and per source IP (Redis counter). Successful login resets the counter.
- Login endpoint rate-limited per IP and per account (Redis).
- Generic error on bad credentials ("invalid email or password") — no user
  enumeration. Same response time for unknown vs known user (constant-time
  compare / dummy hash).
- Ingestion rate limit is **fail-closed** (reject on limiter failure); read-API
  rate limit is fail-open **with an alert** to avoid a Redis outage taking down
  the SOC view.

## 4. Tenant isolation

- Postgres: repository layer injects `WHERE tenant_id = :ctx_tenant` on every
  query for a tenant-scoped table; **no code path** accepts a caller-supplied
  `tenant_id` for scoping. Optional Postgres RLS as defense-in-depth (U-005).
- Neo4j: query builder appends `{tenant_id: $ctx_tenant}` to every node match;
  traversals cannot cross tenants (no relationship spans tenants — graph
  invariant).
- Kafka: consumers filter by `tenant_id`; topic partitioning by tenant.
- Redis / S3: tenant-prefixed keys / object prefixes.
- **Tests:** `tests/security/` includes, for every list/detail/query/mutation
  endpoint, a cross-tenant attempt that must return 403/404 (never another
  tenant's data) — a Phase-1 gate for the auth surface, extended each phase.

## 5. HTTP hardening (api-gateway, ingestion-gateway)

- Request body cap `SM_HTTP_MAX_BODY_BYTES` (default 1 MiB; ingestion has its own
  higher, bounded cap per content type).
- Request timeout `SM_HTTP_REQUEST_TIMEOUT_S`.
- CORS: explicit origin allow-list `SM_CORS_ALLOWED_ORIGINS`; **wildcard rejected
  at config validation when `SM_ENV=production`**; credentials mode only with
  explicit origins.
- Security headers: `Strict-Transport-Security` (prod), `X-Content-Type-Options:
  nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Content-Security-Policy` (frontend), `Permissions-Policy` minimal.
- Per-route rate limits (`SM_RATE_LIMIT_PER_MINUTE` default + overrides).
- No stack traces, DB errors, or internal identifiers in responses (canonical
  error contract only). `SM_ENV != production` may include a `debug` block; prod
  never does.

## 6. Injection & unsafe execution

| Vector | Control |
|---|---|
| SQL | SQLAlchemy parameterized only; `ruff` bans raw string SQL; no f-string/`%`/`+` into `text()` |
| Cypher | parameterized only; LLM never emits executed Cypher (ADR-015); read-only role on the query path; depth + row + time caps |
| Mass assignment | request models are explicit allow-lists (Pydantic); ORM objects never populated from request dicts; `model_config = ConfigDict(extra='forbid')` on all request schemas |
| SSRF | no user-controlled URLs in outbound calls; provider endpoints are config, not input; egress proxy allow-list; block link-local/metadata IP ranges |
| Path traversal | no user-controlled filesystem or S3 keys; report/artifact keys are server-generated UUIDs |
| Prompt injection | retrieved content wrapped + labeled as data; tool allow-list per task; injection heuristics + audit; the LLM's output is validated (`QueryPlan` schema / explanation schema) before any use |
| Deserialization | JSON only; no `pickle` across trust boundaries (model artifacts loaded only from the trusted registry, integrity-checked) |

## 7. Secrets

- Loaded from environment (local) / K8s Secrets + External Secrets Operator
  (prod). Never in source, never in logs, never in error output, never in events.
- `packages/common-py` provides a redaction filter (regex + known-key set)
  applied to all log records and to error serialization.
- `.env` is git-ignored; `.env.example` has placeholders only.

## 8. Audit

- Append-only `audit_log` (no UPDATE/DELETE grant to app role). Per-tenant hash
  chain (`hash = sha256(prev_hash ‖ canonical(row))`) to make tampering
  detectable.
- Recorded: authentication (success/failure), authorization denials, privileged
  reads (cross-tenant operator actions), role/permission grants, hunt queries,
  LLM prompts + tool calls, response actions + approvals, config changes,
  sensor registration.
- Audit-write failure is itself logged + metered; for the most sensitive actions
  (response actions), audit write is in the same transaction as the action
  record.

## 9. AI/agent safety (design; implemented in later phases)

- Agents run under constrained service principals with a **task-scoped tool
  allow-list**; no agent can grant itself tools or roles.
- LLM output → deterministic validation → (for queries) authorized read-only
  execution / (for actions) policy + approval + blast-radius + rollback.
- `SM_RESPONSE_MODE=auto` rejected outside production + signed policy (ADR-022).
- Simulation/deception outputs are labeled and cannot trigger real response
  actions.

## 10. Data protection

- TLS in transit everywhere in production (ingress, service mesh, DB
  connections). Local dev may use plaintext on a private network.
- Encryption at rest: managed DB + S3 SSE in production.
- PII minimization: telemetry payloads carry identifiers, not content bodies,
  where the detection value does not require the body; field-level redaction
  rules before events cross an export boundary.
