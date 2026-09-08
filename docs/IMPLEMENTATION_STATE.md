# SentinelMesh — Implementation State

**This file is authoritative for "where we are" and "what to do next".**
Update it at the end of every coherent implementation unit.

---

## Current phase

**Phase 1 — Foundation + Configuration + Database + Authentication. IN PROGRESS.**
(Phase 0 COMPLETE; architecture LOCKED 2026-09-08.)

## Current implementation unit

Phase 1, Unit 2 — `packages/common-py` infrastructure clients (async Postgres
engine/session/transaction, Redis client, OIDC client, OpenTelemetry + Prometheus
bootstrap, audit hash-chain primitives). **Done + verified.** Next: Unit 3
(Alembic migrations + ORM models + DB-bound `AuditWriter`).

Phase 1 units: 1 ✅ primitives · 2 ✅ infra clients · 3 migrations+models ·
4 `services/api-gateway` · 5 `deploy/docker` · 6 e2e tests + `Makefile`/CI + doc promotion.

## Architecture lock status

**LOCKED** (2026-09-08).

`LOCKED` means: the architecture documentation, decisions, and contracts satisfy
the Phase-0 lock criteria and contain no unresolved critical contradiction. It
does **not** mean any of the following (Engineering Constitution §3): the system
is implemented, deployed, integrated, benchmarked, security-audited, or that any
ML performance is validated. No such claim exists anywhere in this repository.

### Lock criteria checklist

| Criterion | State |
|---|---|
| All 38 requirements analyzed | DONE (`REQUIREMENTS_TRACEABILITY.md`) |
| All 38 requirements mapped | DONE |
| System boundaries defined | DONE (`architecture/overview.md`) |
| Trust boundaries defined | DONE (TB-1..TB-7) |
| Security boundaries defined | DONE (`architecture/security-model.md`) |
| Service boundaries defined | DONE (`architecture/service-catalog.md`, 18 logical services + 3 shared packages + frontend) |
| Service dependency graph defined | DONE (acyclic, documented) |
| Synchronous flows defined | DONE (`overview.md §5`) |
| Asynchronous flows defined | DONE (`overview.md §6`, `event-model.md`) |
| Telemetry flow defined | DONE |
| Event flow defined | DONE (`event-model.md`) |
| Graph flow defined | DONE (`data-model.md`, ADR-011) |
| Detection flow defined | DONE |
| Threat-intelligence flow defined | DONE |
| ML/AI flow defined | DONE (ADR-012..015, `CONTRACTS.md §6–7`) |
| Frontend flow defined | DONE (`CONTRACTS.md §8`) |
| Simulation flow defined | DONE |
| Reporting flow defined | DONE |
| Observability architecture defined | DONE (ADR-020) |
| Deployment architecture defined | DONE (`architecture/deployment.md`) |
| PostgreSQL model defined | DONE (Phase-1 tables in full; later tables listed, per-phase migrations pending) |
| Neo4j model defined | DONE (canonical labels/edges/invariants) |
| Redis usage defined | DONE (ADR-009 namespace table) |
| Kafka architecture defined | DONE (`event-model.md §3`) |
| Flink responsibilities defined | DONE (`event-model.md §7`) — engine choice has open questions U-001/U-002 (non-blocking) |
| Event contracts defined | DONE — canonical `EventEnvelope` **implemented + validated** (`sm_contracts.events`); payloads DRAFT per phase |
| API boundaries defined | DONE — `CONTRACTS.md §1`; Phase-1 request/response models **implemented** (`sm_contracts.api`); later endpoints land per phase |
| ML contracts defined | DONE (template `CONTRACTS.md §6`; per-model contracts land in P5) |
| Security architecture defined | DONE |
| Failure model defined | DONE (`architecture/failure-model.md`) |
| Repository structure defined | DONE (`architecture/repository.md` + skeleton created) |
| Technology decisions documented | DONE (`ARCHITECTURE_DECISIONS.md`, ADR-001..024) |
| Architecture decisions documented | DONE |
| Contracts documented + core implemented | DONE — `packages/contracts-py` implements the envelope, canonical error contract, Phase-1 entity + API models; 19 tests pass; `mypy --strict` clean; JSON Schema generated |
| Requirements traceability documented | DONE |
| Implementation state updated | DONE (this file) |
| No unresolved critical architectural contradiction | DONE — consistency-review pass completed; see `architecture/consistency-review.md` |

### Lock rationale

The three items that held lock in the prior revision are closed:

1. **Contracts materialized.** `packages/contracts-py` now contains executable,
   type-checked, tested Pydantic v2 models for the envelope, error contract, and
   Phase-1 entities/APIs. `scripts/gen_contracts.py` emits JSON Schema
   (`packages/contracts-ts/schemas/`) with a `--check` CI mode.
2. **`CLAUDE.md` reviewed** against the architecture docs — no contradiction
   (`architecture/consistency-review.md`).
3. **Consistency-review pass done** — two doc inconsistencies found and fixed
   (service count 21→18; `identity_link` ownership); recorded in
   `architecture/consistency-review.md`.

## Completed files (Phase 0)

**Docs / config (created):**
`README.md`, `.gitignore`, `.env.example`, `pyproject.toml`, `CLAUDE.md`,
`docs/ARCHITECTURE_DECISIONS.md`, `docs/CONTRACTS.md`,
`docs/REQUIREMENTS_TRACEABILITY.md`, `docs/IMPLEMENTATION_STATE.md`,
`docs/architecture/{repository,overview,service-catalog,data-model,event-model,security-model,failure-model,deployment,consistency-review}.md`,
monorepo skeleton (50 dirs; 18 `services/`, `packages/`, `frontend/web/`, `ml/`,
`deploy/`, `migrations/`, `tests/`, `scripts/`).

**`packages/contracts-py` (created + verified):**
`pyproject.toml`, `README.md`,
`src/sm_contracts/{__init__,version,common,enums,errors,events,jsonschema}.py`,
`src/sm_contracts/entities/{__init__,tenant,user,rbac,sensor,audit}.py`,
`src/sm_contracts/api/{__init__,auth,users,health,pagination}.py`,
`tests/{test_envelope,test_errors,test_entities}.py`.

**`packages/contracts-ts` (created):**
`package.json`, `README.md`, `schemas/*.json` (22 generated JSON Schema files).

**Tooling (created):** `scripts/gen_contracts.py`.

**Modified in Phase 0 close:** `pyproject.toml` (ruff line-length 120,
`known-first-party`, `scripts/**` ignores; dropped `disallow_any_explicit` with
rationale), `.gitignore` (generated TS), `docs/IMPLEMENTATION_STATE.md`,
`docs/CONTRACTS.md` (change log), `docs/architecture/service-catalog.md`
(`identity_link` fix).

## Completed files (Phase 1, Unit 1)

**`packages/common-py` (created + verified):**
`pyproject.toml`, `README.md`,
`src/sm_common/{__init__,config,logging,redaction,context,ids,clock,errors}.py`,
`src/sm_common/security/{__init__,passwords,jwt_internal}.py`,
`src/sm_common/observability/{__init__,health}.py`,
`src/sm_common/fastapi/{__init__,middleware,exception_handlers,hardening}.py`,
`tests/{conftest,test_config,test_ids,test_redaction,test_passwords,test_jwt_internal,test_fastapi,test_health,test_errors}.py`.

**Modified:** `pyproject.toml` (pytest `--import-mode=importlib` + `asyncio_mode`;
`**/errors.py` N818 ignore).

## Completed files (Phase 1, Unit 2)

**`packages/common-py` (created):**
`src/sm_common/db/{__init__,engine,session}.py`,
`src/sm_common/cache/{__init__,redis}.py`,
`src/sm_common/audit/{__init__,hashing}.py`,
`src/sm_common/observability/{metrics,tracing}.py`,
`src/sm_common/security/oidc.py`,
`tests/{test_audit_hashing,test_infra_clients,test_oidc}.py`.

**Modified:** `src/sm_common/observability/{__init__,health}.py`
(`probe_check` + `Pingable`), `src/sm_common/security/__init__.py` (OIDC exports),
`packages/common-py/pyproject.toml` (infra deps).

## APIs

Defined; Phase-1 request/response models implemented in `sm_contracts.api`
(`LoginRequest/Response`, `LogoutResponse`, `MeResponse`, `CreateUserRequest`,
`GrantRoleRequest`, `RoleSummary`, `UserResponse`, `CursorPage`,
`HealthResponse`, `ReadyResponse`, `MetaResponse`, `DepStatus`). Endpoints
themselves (`CONTRACTS.md §1.2`) are **not implemented** — Phase 1. Base
`/api/v1`. Canonical error contract implemented (`sm_contracts.errors`).

## Events

Canonical `EventEnvelope[PayloadT]` **implemented + validated** with envelope
rules (UTC normalization, producer format, clock-skew guard). `EventType`
registry present. Phase-1 payload `UserEventPayload` implemented;
`EVENT_PAYLOAD_REGISTRY` maps it. All other payloads DRAFT (not implemented).
Topic catalog + semantics in `event-model.md`. Exactly-once not claimed.

## Schemas / migrations

- `sm_contracts` JSON Schema: 22 files in `packages/contracts-ts/schemas/`
  (regenerate: `python scripts/gen_contracts.py`; CI: `--check`).
- Postgres: Phase-1 tables fully specified in `data-model.md`
  (`tenant`, `user`, `role`, `permission`, `user_role`, `role_permission`,
  `sensor`, `audit_log`). `identity_link` is **Phase 2** (owned by
  `normalization-engine`). **No migration files yet** — `migrations/postgres/`
  is an empty Alembic tree, initialized in Phase 1.
- Neo4j: constraint/index migration `neo4j/0001` specified, not written.

## Dependencies

- `packages/contracts-py`: `pydantic[email]>=2.9,<3`; dev `pytest>=8`.
- `packages/common-py`: `sm-contracts`, `pydantic>=2.9,<3`,
  `pydantic-settings>=2.5,<3`, `structlog>=24.4`, `argon2-cffi>=23.1`,
  `pyjwt>=2.9,<3`, `fastapi>=0.115,<1`; dev `pytest`, `pytest-asyncio>=0.24`,
  `httpx>=0.27`.
  `pyjwt>=2.9,<3`, `fastapi>=0.115,<1`, `httpx>=0.27`, `anyio>=4`,
  `sqlalchemy[asyncio]>=2.0,<3`, `asyncpg>=0.29`, `redis>=5,<6`,
  `prometheus-client>=0.20`, `opentelemetry-sdk>=1.27`,
  `opentelemetry-exporter-otlp-proto-http>=1.27`; dev `pytest`,
  `pytest-asyncio>=0.24`, `respx>=0.21`.
- Verified installed in `.venv` (Python 3.11.5): pydantic **2.13.5**,
  SQLAlchemy **2.0.52**, plus pydantic-settings, structlog, argon2-cffi, pyjwt,
  fastapi, httpx, asyncpg, redis, prometheus-client, opentelemetry-sdk, respx.
- OIDC is done with `httpx` + `pyjwt` (`PyJWKClient` wrapped via `anyio.to_thread`);
  no `authlib`. Phase 1 Unit 3 adds `alembic`.

## Environment variables

All in `.env.example` (57 keys, tagged `[required]`/`[optional]`/`[secret]`).
Typed loader + startup validation is Phase 1 (`packages/common-py`).

## Verification performed (Phase 0)

| Check | Command | Result |
|---|---|---|
| Local toolchain | `Get-Command` git/python/node/npm/docker/uv/pnpm/helm/kubectl/java | git 2.55.0, Python 3.11.5, Node 24.14.0, npm 11.9.0, Java 8 present; **docker, uv, pnpm, helm, kubectl, JDK≥11 absent** (ADR-001) |
| Repo skeleton | `mkdir` / `find` | 50 directories under `C:\Users\gmalh\sentinelmesh` |
| Requirements coverage | `grep -c '^### R' docs/REQUIREMENTS_TRACEABILITY.md` | **38** |
| Source hierarchy explicit | manual | PRIMARY (38-point) > SECONDARY (Blueprint) stated in README, ADR intro, traceability intro, CLAUDE.md |
| Fabricated-claim scan | `grep -rniE '(ROC-AUC\|F1 score\|... \|deployed successfully\|benchmark achieved)' docs/ README.md CLAUDE.md` | only negations/prohibitions matched — **no fabricated value** |
| `contracts-py` install | `pip install -e "packages/contracts-py[dev]"` (in `.venv`) | OK; pydantic 2.13.5 |
| Contract unit tests | `python -m pytest packages/contracts-py -q` | **19 passed** |
| Type check | `python -m mypy --strict --python-version 3.11 packages/contracts-py/src/sm_contracts` | **Success: no issues found in 18 source files** |
| Lint | `python -m ruff check packages/contracts-py scripts/gen_contracts.py` | **All checks passed** |
| Schema codegen | `python scripts/gen_contracts.py` then `--check` | 22 JSON Schema files written; `--check` → "up to date" |
| git | `git init` + commits | `0b91ed2` (Phase 0 docs) + Phase-0-close commit |

**Not verified (Phase 0):** anything requiring Docker, Kubernetes, Flink,
Neo4j, Kafka, a GPU, LLM providers, TI providers, or a cloud account. TypeScript
generation was **not run** (`json-schema-to-typescript` not installed — needs
`npm install` under `packages/contracts-ts`); JSON Schema generation is
verified. No runtime service code exists.

## Verification performed (Phase 1, Unit 1 — `common-py`)

| Check | Command | Result |
|---|---|---|
| Install | `pip install -e "packages/common-py[dev]"` (in `.venv`) | OK |
| Unit tests | `python -m pytest packages -q` | **64 passed** (19 contracts + 45 common) |
| Type check | `python -m mypy --strict --python-version 3.11 packages/common-py/src/sm_common` | **Success: no issues found in 17 source files** |
| Lint | `python -m ruff check packages/common-py` | **All checks passed** |

Covered by tests: config defaults + `service_name` required + pool bounds +
**production guards** (CORS `*`, missing secrets, `response_mode=auto` outside
production, `auto` needs policy) + `frozen`; `uuid7` version/variant/ordering;
redaction (sensitive keys, bearer/DSN/JWT patterns, recursion); Argon2id
hash/verify/dummy/empty/malformed/salt; internal JWT roundtrip + wrong
audience/key + rotation + expiry; `SmError` → canonical response + message
redaction; FastAPI request-id echo/preserve, security headers, canonical SmError
body, masked 500, validation-error shape, 413 body-size limit; liveness +
readiness (ok / required-fail / optional-fail / timeout / empty).

**Not verified (Phase 1, Unit 1):** nothing requiring Docker (no Postgres/Redis
client yet — Unit 2); no live OIDC; no OTel exporter. `structlog`/`starlette`
`httpx`-testclient deprecation warnings present, non-blocking.

## Verification performed (Phase 1, Unit 2 — infra clients)

| Check | Command | Result |
|---|---|---|
| Install | `pip install -e "packages/common-py[dev]" respx` | OK; SQLAlchemy 2.0.52 |
| Unit tests | `python -m pytest packages -q` | **81 passed** (19 contracts + 62 common) |
| Type check | `python -m mypy --strict --python-version 3.11 packages/common-py/src/sm_common` | **Success: no issues found in 27 source files** |
| Lint | `python -m ruff check packages/common-py` | **All checks passed** |

Covered by tests (no live infrastructure): engine URL + bounded pool size;
`Database.dispose()` clean with no connection opened; `Cache.key()` prefixing;
`build_redis` constructs without connecting; Prometheus metrics increment +
`render_latest` output + registry isolation; tracing **no-op** when
`SM_OTEL_EXPORTER_OTLP_ENDPOINT` unset (span still works); audit hash chain —
canonical-JSON determinism, hash stability, `verify_chain` detects body tamper
and reorder; OIDC — PKCE `S256` challenge, `authorization_url` params, discovery
issuer-mismatch → `DependencyUnavailable`, code-exchange failure →
`Unauthenticated`, ID-token `aud`/`nonce` checks (signing key stubbed).

**Not verified (Phase 1, Unit 2):** live Postgres / Redis connections, real OIDC
provider, real OTLP collector, JWKS fetch (`PyJWKClient` path) — all need Docker
or network and are Unit 6 / integration. Docker still absent.

## External infrastructure requirements (accumulated)

| Need | For | Status |
|---|---|---|
| Docker Desktop | local `docker-compose` (Postgres, Redis, Keycloak, Redpanda, Neo4j, MinIO, Prometheus, Grafana, MLflow) | **NOT INSTALLED** — required from Phase 1 for integration tests |
| `npm install` under `packages/contracts-ts` | TypeScript contract types for the frontend | not run — JSON Schema is committed; TS is generated on demand |
| JDK 11+ | Apache Flink jobs | **NOT INSTALLED** — Phase 3+ |
| GPU + CUDA | GNN / autoencoder / predictive training at dataset scale | not available — Phase 5 |
| LLM provider credentials | AI analyst / agents / NL hunting / storytelling / RCA | not provided — Phase 6 |
| Threat-intel provider credentials (abuse.ch / OTX / …) | live TI enrichment (optional/flagged) | not provided — Phase 3 optional |
| MaxMind GeoLite2 DB | Geo-IP enrichment | not provided — Phase 2 (degrades gracefully) |
| CICIDS2017 dataset | benchmark parity with architecture | not staged (NSL-KDD, UNSW-NB15, CTU-13, EMBER, LANL staged at `C:\Sentinel_Mesh`) |
| Neo4j Enterprise / GDS production license | production multi-tenant scale, clustering, RBAC (U-003/U-008) | decision required before production |
| Kubernetes cluster + Helm + kubectl | production deployment (R38) | not available |

## Known limitations / open questions

- Open architecture questions **U-001 … U-010** in `ARCHITECTURE_DECISIONS.md`.
  **None blocks Phases 1–4.**
- Per-service `README.md` files (R27) are added as each service is implemented.
- CICIDS2017 not staged.
- Generic `EventEnvelope[T]` JSON Schema is exported only at concrete
  parameterizations listed in `sm_contracts.jsonschema.SCHEMA_MODELS`; each new
  payload must be added there when implemented.

## Exact next action

**PHASE 1, Unit 3 — ORM models + migrations + audit writer:**

- `packages/common-py/src/sm_common/db/models.py`: SQLAlchemy 2 declarative
  models for the Phase-1 tables (`Tenant`, `User`, `Role`, `Permission`,
  `UserRole`, `RolePermission`, `Sensor`, `AuditLog`) — UUIDv7 PKs,
  `tenant_id` FKs, unique/check constraints, indexes, `created_at`/`updated_at`
  (trigger-maintained), `deleted_at` where lifecycle needs it. These models are
  the shared schema; `api-gateway` is the only writer (ADR / service-catalog).
- `sm_common/audit/writer.py`: `AuditWriter` — given an `AsyncSession`, reads the
  tenant's last chain hash `... FOR UPDATE`, computes `compute_entry_hash`,
  inserts the row in the caller's transaction. For response-critical actions the
  audit insert shares the action's transaction.
- `migrations/postgres/`: `alembic.ini` + `env.py` (async engine, `target_metadata`
  = models' `MetaData`); migration `0001_initial` (all 8 tables, full
  constraints/indexes, `updated_at` trigger function); migration `0002_seed`
  (permission catalog from `PermissionCode`, system roles from `SystemRole`,
  role→permission grants).
- Tests: model constraint round-trips + `AuditWriter` chain continuity **against
  a real Postgres** (docker-compose, `integration` marker — **blocked until
  Docker is installed**); offline: migration `upgrade head` / `downgrade base` /
  `upgrade head` on SQLite-incompatible? use a Postgres testcontainer or skip —
  decide in Unit 3; Alembic script lints (`alembic check`).

Then **Unit 4** = `services/api-gateway`. **Unit 5** = `deploy/docker`
(compose brings the first real Postgres/Redis — unblocks the integration tests).
**Unit 6** = end-to-end Phase-1 tests + `Makefile`/CI + doc promotion.

Original Phase-1 step list (for reference):

1. ~~`packages/common-py` config/logging/errors/IDs/security/health/FastAPI~~ —
   **DONE (Unit 1).**
1b. ~~`packages/common-py` DB engine/session/transaction, Redis client, OIDC
   client, OTel + Prometheus, audit hash-chain primitives~~ — **DONE (Unit 2).**
2. `migrations/postgres`: init Alembic; `0001` = Phase-1 tables
   (`tenant`, `user`, `role`, `permission`, `user_role`, `role_permission`,
   `sensor`, `audit_log`) — full PK/FK/unique/check/index + `updated_at` trigger;
   `0002` seed = permission catalog (`PermissionCode`) + system roles
   (`SystemRole`) + role→permission grants. CI runs `upgrade head` /
   `downgrade base` / `upgrade head` on a scratch DB.
3. `services/api-gateway`: FastAPI app; `/healthz`, `/readyz`, `/health/deps`,
   `/api/v1/meta`; local login (`/api/v1/auth/login` — Argon2id, lockout,
   constant-time, no user enumeration); OIDC login + callback; logout; session
   cookie (httpOnly/Secure/SameSite) + Redis session store + CSRF token;
   `get_current_principal` dependency; `require_permission(...)` dependency
   (deny-by-default); tenant-scoped repository layer (injected predicate, never
   client-supplied); `/api/v1/me`; `/api/v1/admin/users` (list paginated,
   create) + `/api/v1/admin/roles` (list) + `/api/v1/admin/users/{id}/roles`
   (grant, audited); HTTP hardening (body cap, timeout, CORS allow-list with
   prod-wildcard rejection, security headers, per-route rate limit). Responses
   use `sm_contracts.api` models only — no ORM objects.
4. `deploy/docker`: `Dockerfile.app`, `docker-compose.yml` (postgres, redis,
   keycloak, prometheus, grafana, app) — service-name networking, health gating.
5. Tests (`tests/` + per-package): config validation; Argon2id hash/verify;
   login success / lockout / invalid credentials; permission enforcement;
   **cross-tenant isolation** (list / detail / role-grant must 403/404);
   invalid payload → canonical error shape; migration up/down/up on a scratch
   DB; health / readiness behavior. Integration tests use compose Postgres/Redis
   (real infra, not mocked).
6. Tooling: per-service `pyproject.toml`; `Makefile`/`justfile`
   (`setup`, `migrate`, `run`, `test`, `lint`, `typecheck`, `fmt`); wire
   `ruff` + `mypy --strict` + `pytest` in CI.
7. Docs: update this file; `CONTRACTS.md` (promote Phase-1 API/entity contracts
   DRAFT → STABLE); `REQUIREMENTS_TRACEABILITY.md` (R1 `sensor` model, R23
   health/logging/request-IDs, R38 auth/RBAC/SSO foundation →
   PARTIALLY IMPLEMENTED / LOCALLY VERIFIED as actually verified).

## Change log

| Date | Phase | Change |
|---|---|---|
| 2026-09-08 | 0 | Repo created at `C:\Users\gmalh\sentinelmesh`; skeleton + doc set; ADR-001…024; all 38 requirements traced. Commit `0b91ed2`. Status: NOT LOCKED. |
| 2026-09-08 | 0 (close) | `packages/contracts-py` implemented (envelope, error contract, Phase-1 entities + APIs, enums); `scripts/gen_contracts.py` + `packages/contracts-ts` schemas; consistency-review pass (2 fixes). Verified: pytest 19 passed, mypy --strict clean, ruff clean, codegen + `--check` pass. **Architecture status: LOCKED.** |
| 2026-09-08 | 1 (Unit 1) | `packages/common-py` platform primitives: `config` (typed `AppSettings`, startup validation, production guards), `logging` (structlog JSON + redaction), `redaction`, `context`, `ids` (uuid7), `clock`, `errors` (`SmError` → canonical `ErrorResponse`), `security.passwords` (Argon2id + dummy-verify), `security.jwt_internal` (mint/verify + rotation), `observability.health`, `fastapi` (request-context middleware, exception handlers, security headers, body-size limit, CORS builder). Verified: **pytest 64 passed** (19+45), mypy --strict clean (17 files), ruff clean. Root pytest `--import-mode=importlib`; ruff `line-length=120`, `**/errors.py` N818 ignore. |
| 2026-09-08 | 1 (Unit 2) | `packages/common-py` infra clients: `db` (async SQLAlchemy 2 engine, `Database` session/`transaction()`/`ping`), `cache.redis` (`Cache` + key prefix + `ping`), `security.oidc` (`OidcClient` — discovery cache, PKCE `S256`, auth URL, code exchange, ID-token verify via `PyJWKClient`+`anyio.to_thread`), `observability.metrics` (`Metrics` + per-process registry), `observability.tracing` (OTLP bootstrap, no-op without endpoint), `audit.hashing` (per-tenant hash chain primitives). Verified: **pytest 81 passed** (19+62), mypy --strict clean (27 files), ruff clean. Deps added: sqlalchemy[asyncio], asyncpg, redis, prometheus-client, opentelemetry-sdk + otlp-http, httpx, anyio; dev respx. |
