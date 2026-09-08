# api-gateway

The frontend's **only** backend (BFF). Owns authentication, deny-by-default
RBAC, tenant-scoped reads, and the audit trail for user-facing actions. The
browser never talks to Postgres, Redis, Neo4j, Kafka or any provider API.

## Endpoints (Phase 1)

| Method | Path | Auth | Permission |
|---|---|---|---|
| GET | `/healthz` | none | none |
| GET | `/readyz` | none | none (503 when a required dependency is down) |
| GET | `/health/deps` | session | `ops:read` |
| GET | `/api/v1/meta` | none | none |
| POST | `/api/v1/auth/login` | credentials | none |
| GET | `/api/v1/auth/oidc/login?tenant=<slug>` | none | none |
| GET | `/api/v1/auth/oidc/callback` | state | none |
| POST | `/api/v1/auth/logout` | session + CSRF | none |
| GET | `/api/v1/me` | session | none |
| GET | `/api/v1/admin/users` | session | `users:read` |
| POST | `/api/v1/admin/users` | session + CSRF | `users:create` |
| GET | `/api/v1/admin/roles` | session | `roles:read` |
| POST | `/api/v1/admin/users/{id}/roles` | session + CSRF | `roles:grant` |

Every response body is an `sm_contracts` model. Errors always use the canonical
`ErrorResponse`. Lists are cursor-paginated with a server-capped `limit`.

## Security properties

- **Session:** opaque id in an httpOnly/Secure/SameSite=Lax cookie. All
  authoritative state (user, tenant) lives server-side in Redis. Sliding idle
  expiry plus a hard absolute deadline.
- **Privileges are never cached in the session.** Roles and permissions are
  re-resolved from the database on every request, so revoking a role takes
  effect on the next call.
- **CSRF:** double-submit. `sm_csrf` cookie (readable) must be echoed in
  `X-CSRF-Token` on every unsafe method and must match the server-side record.
- **Tenant isolation:** the tenant always comes from the principal. No route,
  request model, or repository method accepts a caller-supplied `tenant_id`.
  A user in another tenant is reported as `not_found`, never as `forbidden`, so
  the API cannot be used to probe for existence.
- **Local login:** Argon2id; `dummy_verify` on unknown tenant/user/federated
  account so timing does not leak; one generic `invalid email or password` for
  every failure mode; `failed_login_count` + `locked_until` lockout; every
  attempt audited with the real reason recorded server-side only.
- **OIDC:** authorization code + PKCE (S256) + single-use `state` + `nonce`.
  Unknown subjects are **not** auto-provisioned; a user must already exist in
  the tenant.
- **HTTP:** body-size cap, security headers, CORS allow-list (wildcard rejected
  in production), request/correlation ids on every response and log line.

## Run locally

```
pip install -e "packages/contracts-py[dev]" -e "packages/common-py[dev]" -e "services/api-gateway[dev]"
cp .env.example .env      # then fill SM_PG_PASSWORD, SM_INTERNAL_JWT_SIGNING_KEY, SM_OIDC_CLIENT_SECRET
python -m sm_api_gateway   # needs Postgres + Redis (docker-compose arrives in Unit 5)
```

## Test

```
pytest services/api-gateway            # in-memory fakes; no Docker needed
mypy --strict services/api-gateway/src/sm_api_gateway
ruff check services/api-gateway
```

The unit tests build the **real** app — real routing, middleware,
authentication, `require_permission` and exception handlers — and replace only
Postgres and Redis with in-memory fakes. Tests that need genuine SQL behaviour
(constraints, the audit advisory lock, applied migrations) are integration tests
and arrive with docker-compose in Unit 5.
