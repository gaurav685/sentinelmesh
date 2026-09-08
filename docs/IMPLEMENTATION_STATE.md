# SentinelMesh — Implementation State

**This file is authoritative for "where we are" and "what to do next".**
Update it at the end of every coherent implementation unit.

---

## Current phase

**Phase 1 — Foundation + Configuration + Database + Authentication. IN PROGRESS.**
(Phase 0 COMPLETE; architecture LOCKED 2026-09-08.)

## Current implementation unit

Phase 1, Unit 6 — **PARTIAL, and blocked.**

Done: the CI workflow (`.github/workflows/ci.yml`), the
`SM_REQUIRE_INTEGRATION` guard that stops a skipped integration test from
reading as a pass, 14 offline CI-config checks, and a rewritten `README.md`.

**Blocked on Docker, which is still not installed.** Unit 6 steps 1-3 — run the
integration suite, fix what it exposes, drive an end-to-end OIDC sign-in — cannot
start until it is. Phase 1 is **not** complete and must not be called complete.

Phase 1 units: 1 ✅ primitives · 2 ✅ infra clients · 3 ✅ models+migrations ·
4 ✅ api-gateway · 5 ⚠️ deploy/docker authored but unverified ·
6 ⚠️ CI authored; integration run, e2e and doc promotion still blocked.

> **The single outstanding blocker for Phase 1 is Docker.** Two ways to clear it:
> install Docker Desktop locally and run `make up` then `make test-integration`,
> **or** push this repository to GitHub and let the `integration` and `image` CI
> jobs run — those runners have Docker. Either produces the real verification;
> until one of them happens, 49 tests remain unexecuted.

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

## Completed files (Phase 1, Unit 3)

**Created:** `packages/common-py/src/sm_common/db/{base,models}.py`,
`packages/common-py/src/sm_common/audit/writer.py`,
`migrations/postgres/{alembic.ini,env.py,script.py.mako}`,
`migrations/postgres/versions/{0001_initial.py,0002_seed_rbac.py}`,
`packages/common-py/tests/{test_models,test_audit_writer}.py`,
`tests/contract/test_migrations_offline.py`.

**Modified:** `packages/common-py/src/sm_common/db/__init__.py` (model exports),
`packages/common-py/src/sm_common/audit/__init__.py` (`AuditWriter` export),
`packages/common-py/README.md`.

## Completed files (Phase 1, Unit 4)

**Created:** `services/api-gateway/{pyproject.toml,README.md}`,
`src/sm_api_gateway/{__init__,__main__,version,app,deps,mappers}.py`,
`src/sm_api_gateway/security/{__init__,principal,session,cookies,login}.py`,
`src/sm_api_gateway/repositories/{__init__,protocols,sql}.py`,
`src/sm_api_gateway/routes/{__init__,health,auth,admin}.py`,
`services/api-gateway/tests/{conftest,test_health,test_auth_login,test_authz,test_tenant_isolation}.py`.

**Modified:** `packages/common-py/src/sm_common/config.py` (session cookie names,
idle/absolute session lifetimes, OIDC state TTL, login lockout settings),
`.env.example` (7 new keys), `pyproject.toml` (ruff `flake8-bugbear
extend-immutable-calls` for the FastAPI dependency idiom, `sm_api_gateway`
first-party).

## Verification performed (Phase 1, Unit 4 — api-gateway)

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest packages services tests -q` | **143 passed** (41 new) |
| Type check | `python -m mypy --strict --python-version 3.11` over all three packages | **Success: no issues found in 66 source files** |
| Lint | `python -m ruff check packages services tests migrations` | **All checks passed** |
| Contract schema | `python scripts/gen_contracts.py --check` | up to date |

Covered by tests: login success (cookies + CSRF header + permissions, no
password echoed); failure counter reset; wrong password / unknown user /
unknown tenant returning byte-identical generic errors; lockout at the
threshold; suspended tenant; non-active user; federated-only account;
invalid-payload and unknown-field rejection through the canonical error
contract; no session / unknown session / missing CSRF / wrong CSRF; missing
permission denied **and audited**; granted permission allowed; role revocation
taking effect on the next request; deactivated-user session dropped; invalid
cursor and over-cap limit rejected; liveness unaffected by a dead dependency;
readiness returning 503 with the failing dependency named; `/health/deps`
gated on `ops:read`; and cross-tenant isolation on user list, user create, role
grant and `/me`, with `not_found` (never `forbidden`) for another tenant's user.

**Not verified (Phase 1, Unit 4):** nothing has run against a real Postgres,
Redis or OIDC provider. The SQL repositories, the Redis session store and the
OIDC client are exercised only through in-memory fakes. Docker is being
installed; integration tests land in Unit 5.

## Completed files (Phase 1, Unit 5)

**Created:** `deploy/docker/{docker-compose.yml,Dockerfile.app,README.md}`,
`deploy/docker/keycloak/realm-sentinelmesh.json`,
`deploy/prometheus/prometheus.yml`, `.dockerignore`, `Makefile`,
`services/api-gateway/src/sm_api_gateway/routes/metrics.py`,
`tests/contract/test_deploy_local_config.py`,
`tests/integration/{conftest,test_migrations_pg,test_audit_writer_pg,test_models_constraints_pg,test_repositories_pg,test_session_store_redis}.py`.

**Modified:** `services/api-gateway/src/sm_api_gateway/{app,routes/__init__}.py`
(wire the metrics router). Dev dependency added: `pyyaml` (offline compose
checks).

## Verification performed (Phase 1, Unit 5 — local stack)

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest packages services tests -q` | **158 passed, 49 skipped** |
| Deployment config (offline) | `python -m pytest tests/contract/test_deploy_local_config.py -q` | **15 passed** |
| Type check | `python -m mypy --strict --python-version 3.11` over all three packages | **Success: no issues found in 67 source files** |
| Lint | `python -m ruff check packages services tests migrations scripts` | **All checks passed** |

The 15 offline checks assert: compose parses; core services carry no profile and
optional ones carry theirs; **no `localhost`/`127.0.0.1` in any container
environment**; per-service `SM_SERVICE_NAME`; healthchecks on the stateful
services; `app` gated on both dependencies healthy **and** `migrate` completing
successfully; `migrate` gated on postgres and `restart: "no"`;
`${SM_PG_PASSWORD:?...}` fail-fast; declared volumes; the Dockerfile being
multi-stage, non-root (`USER 10001`), health-checked, with no compiler in the
runtime stage; `.dockerignore` excluding `.env`/`.venv`/`.git`; the Prometheus
target matching the app's real port and metrics path; and the Keycloak client
being confidential with PKCE `S256`, the password grant disabled, and exact
callback redirect URIs.

**Not verified (Phase 1, Unit 5) — the important part:** `docker compose config`
has not been run, no image has been built, no container has been started, and
**all 49 integration tests are skipped**. Specifically still unproven at
runtime: the migrations applying to a real database and the
`upgrade -> downgrade -> upgrade` cycle; the seed content; the `updated_at` and
append-only triggers; the per-tenant advisory lock preventing a forked audit
chain under concurrency; every schema constraint; the SQL repositories' tenant
predicate, soft-delete filter, cursor pagination and permissions join; the Redis
session TTL and absolute-deadline behaviour; the OIDC flow against a real
provider; and the `/metrics` endpoint being scraped.

## Completed files (Phase 1, Unit 6 — partial)

**Created:** `.github/workflows/ci.yml`, `tests/contract/test_ci_config.py`.

**Modified:** `tests/integration/conftest.py` (`SM_REQUIRE_INTEGRATION` turns an
unreachable dependency into a failure instead of a skip), `README.md` (rewritten:
real status, real setup commands, explicit honesty note).

## Verification performed (Phase 1, Unit 6 — partial)

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest packages services tests -q` | **172 passed, 49 skipped** |
| CI config (offline) | `python -m pytest tests/contract/test_ci_config.py -q` | **14 passed** |
| Lint | `python -m ruff check packages services tests migrations scripts` | **All checks passed** |
| Skip-guard behaves | same module with and without `SM_REQUIRE_INTEGRATION=1` | **11 skipped** vs **11 errors** — the guard works |

The CI workflow defines four jobs: `static` (ruff + `mypy --strict`), `unit`
(`-m "not integration"` plus `gen_contracts.py --check`), `integration`
(postgres:16 + redis:7 service containers, applies migrations, runs the 49
tests with `SM_REQUIRE_INTEGRATION=1`), and `image` (builds `Dockerfile.app`,
asserts uid 10001, and asserts the production config guard rejects a CORS
wildcard **inside the built image**).

**Not verified (Phase 1, Unit 6):** the workflow has never run — no job, no
image build, no integration execution. Everything listed under *Not verified
(Phase 1, Unit 5)* still stands.

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
- Postgres: 8 Phase-1 tables **implemented** as SQLAlchemy models
  (`sm_common.db.models`) and as Alembic migrations:
  - `0001_initial` — `tenant`, `permission`, `role`, `user`, `user_role`,
    `role_permission`, `sensor`, `audit_log`; full PK/FK/unique/check/index;
    `sm_set_updated_at()` trigger on `tenant`/`user`/`role`/`sensor`;
    `sm_audit_log_immutable()` BEFORE UPDATE OR DELETE trigger on `audit_log`;
    descending `(tenant_id, created_at)` / `(actor_id, created_at)` audit
    indexes. Reversible.
  - `0002_seed_rbac` — 14 permissions, 5 system roles, role→permission grants,
    ids derived via `uuid5` from a fixed namespace (idempotent, exactly
    reversible).
  - Enum columns are `varchar` + `CHECK` rendered from the `sm_contracts`
    enums; a drift-guard test asserts every enum value appears in its CHECK.
  - `identity_link` remains **Phase 2** (owned by `normalization-engine`).
  - **Never applied to a real database** — no Docker (see *Not verified*).
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
  no `authlib`.
- `alembic>=1.13` installed (**1.19.2** verified) for `migrations/postgres`.

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

## Verification performed (Phase 1, Unit 3 — models + migrations + audit writer)

| Check | Command | Result |
|---|---|---|
| Unit + contract tests | `python -m pytest packages tests -q` | **102 passed** |
| Type check | `python -m mypy --strict --python-version 3.11 packages/common-py/src/sm_common` | **Success: no issues found in 30 source files** |
| Lint | `python -m ruff check packages tests migrations` | **All checks passed** |
| Migration DDL compiles | `alembic -c migrations/postgres/alembic.ini upgrade head --sql` | full DDL + seed INSERTs emitted (offline, no connection) |

Covered by tests: exact Phase-1 table set; `tenant_id` nullability per table;
naming convention applied; `user` uniqueness + lowercase-email + non-negative
login-counter checks; `role` two partial unique indexes; `audit_log` shape
(`metadata` column name, unique `hash`, hex-64 format checks, no
`server_default` on `created_at`); **enum drift guard** (every `sm_contracts`
enum value present in its CHECK); `AuditWriter` genesis hash, advisory lock
taken before the last-hash read, chaining, `verify_chain` round-trip, tamper
detection, platform (`tenant_id IS NULL`) entries; offline migration output
contains all 8 tables, both triggers, partial + DESC indexes, and the seed rows.

**Not verified (Phase 1, Unit 3):** the migrations have **never been applied to a
real database**; `AuditWriter` has **never run against Postgres** — the advisory
lock, the last-hash ordering under concurrency, the constraints, and the
append-only trigger are unexercised. `alembic upgrade head` /
`downgrade base` / `upgrade head` against a live database is a Unit 6
integration test. Docker is still absent.

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

**PHASE 1, Unit 6 (remaining) — close out Phase 1.** Blocked until Docker is
available, by either route:

- **Local:** install Docker Desktop, then `make up` followed by
  `make test-integration`.
- **CI:** push this repository to GitHub; the `integration` and `image` jobs run
  on runners that already have Docker.

Then, in order:

1. Record the real output here. Move each item out of the Unit-5 and Unit-6
   "not verified" lists **only** when its test has actually passed.
2. Fix whatever the run exposes. The integration suite has never executed, so
   treat first-run failures as expected work.
3. End-to-end: bring up the `oidc` profile and drive a real sign-in through
   Keycloak (`/api/v1/auth/oidc/login` -> callback -> `/me`), plus a local login
   and one audited admin action, against the running stack.
4. Documentation promotion: update `REQUIREMENTS_TRACEABILITY.md` statuses to
   `INTEGRATION VERIFIED` only for what the run proved; record the residual
   external requirements.
5. Only then declare Phase 1 complete and set the next action to
   **Phase 2 — Telemetry Ingestion + Normalization**.

### Superseded plan for Unit 5 (kept for the record — AUTHORED, NOT EXECUTED)

- `deploy/docker/docker-compose.yml`: `postgres:16`, `redis:7`,
  `quay.io/keycloak/keycloak` (dev realm `sentinelmesh`), `prom/prometheus`,
  `grafana/grafana`, and the `app` (api-gateway) built from
  `deploy/docker/Dockerfile.app`. Neo4j / Redpanda / MinIO / MLflow are declared
  but not required until their phase. Healthchecks plus
  `depends_on: condition: service_healthy`. **Container-to-container addressing
  uses service names** (`SM_PG_HOST=postgres`, `SM_REDIS_URL=redis://redis:6379/0`,
  `SM_OIDC_ISSUER=http://keycloak:8080/realms/sentinelmesh`), never `localhost`.
  Named volumes for postgres/redis data, git-ignored.
- `deploy/docker/Dockerfile.app`: multi-stage, non-root user, installs the three
  packages, entrypoint `python -m sm_api_gateway`.
- A Keycloak realm import file for the dev IdP (`sentinelmesh` realm, the
  `sentinelmesh-api` confidential client, one test user).
- `deploy/prometheus/prometheus.yml` scraping the gateway.
- **Then run the integration work this unlocks** (the first non-offline
  verification in the project):
  - `alembic -c migrations/postgres/alembic.ini upgrade head`, then
    `downgrade base`, then `upgrade head` against the compose Postgres.
  - `tests/integration/`: `AuditWriter` chain continuity and the per-tenant
    advisory lock under concurrent appends; the append-only trigger rejecting
    UPDATE/DELETE; model constraints (unique email per tenant, lowercase-email
    check, role partial unique indexes); `SqlUserRepository` /
    `SqlRoleRepository` behaviour including the tenant predicate; the Redis
    session store TTL/absolute-expiry behaviour.
  - Mark them `integration` and skip cleanly when Docker is unavailable.
- Record in this file exactly which previously-`NOT VERIFIED` items became
  verified, with the commands and their real output.

Then **Unit 6** = end-to-end Phase-1 tests through the running stack (real
login against Keycloak), `Makefile`/`justfile` targets, CI wiring, and the
documentation promotion listed in step 7 below.

### Superseded plan for Unit 4 (kept for the record — DONE)

- `services/api-gateway/pyproject.toml` (depends on `sm-contracts`, `sm-common`,
  `fastapi`, `uvicorn`), `src/sm_api_gateway/`.
- `app.py`: FastAPI factory — `configure_logging`, `configure_tracing`,
  `RequestContextMiddleware`, `SecurityHeadersMiddleware`,
  `BodySizeLimitMiddleware`, `CORSMiddleware` from `build_cors_kwargs`,
  `install_exception_handlers`, lifespan wiring `Database`/`Cache`/`OidcClient`
  and disposing them on shutdown.
- `routes/health.py`: `/healthz` (`liveness`), `/readyz`
  (`evaluate_readiness` over `probe_check(Database)` + `probe_check(Cache)`),
  `/health/deps` (requires `ops:read`), `/api/v1/meta`.
- `security/principal.py`: `Principal` (user id, tenant id, roles, permission
  set) resolved **server-side** from the session; `get_current_principal`
  dependency; `require_permission(code)` dependency that is deny-by-default and
  records `authz_denials` metric + audit entry.
- `security/session.py`: Redis-backed session store (idle + absolute expiry
  from config), httpOnly/Secure/SameSite cookie, CSRF double-submit token.
- `repositories/`: tenant-scoped repositories over `sm_common.db.models`. The
  tenant predicate is injected from `Principal` — no function accepts a caller
  supplied `tenant_id`.
- `routes/auth.py`: `POST /api/v1/auth/login` (Argon2id, `dummy_verify` for
  unknown users, lockout via `failed_login_count`/`locked_until`, generic error,
  audit on success and failure), `GET /api/v1/auth/oidc/login`,
  `GET /api/v1/auth/oidc/callback` (state + PKCE + nonce validated),
  `POST /api/v1/auth/logout`, `GET /api/v1/me`.
- `routes/admin.py`: `GET /api/v1/admin/users` (cursor-paginated),
  `POST /api/v1/admin/users`, `GET /api/v1/admin/roles`,
  `POST /api/v1/admin/users/{id}/roles` (audited). Responses use
  `sm_contracts.api` models only — never an ORM object.
- Tests: login success / invalid / lockout; permission enforcement per route;
  **cross-tenant isolation** (list, detail, role-grant must not reveal another
  tenant's data); invalid payload → canonical error; `/readyz` degraded when a
  dependency probe fails. Anything needing a live Postgres/Redis is marked
  `integration` and skipped until Unit 5 provides docker-compose.

Then **Unit 5** = `deploy/docker` (compose brings the first real Postgres/Redis
and unblocks the integration tests, including applying the migrations).
**Unit 6** = end-to-end Phase-1 tests + `Makefile`/CI + doc promotion.

### Superseded plan for Unit 3 (kept for the record — DONE)

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
| 2026-09-08 | 1 (Unit 6, partial) | `.github/workflows/ci.yml` (static / unit / integration with postgres+redis service containers / image build with non-root and production-config-guard assertions); `SM_REQUIRE_INTEGRATION=1` makes an unreachable dependency a failure rather than a skip, so CI cannot go green on a missing database; 14 offline CI-config checks; `README.md` rewritten with real status and setup. Verified: **pytest 172 passed / 49 skipped**, ruff clean, and the skip-guard exercised directly (11 skipped vs 11 errors). **Workflow never run; no image built; 49 integration tests still unexecuted.** |
| 2026-09-08 | 1 (Unit 5) | `deploy/docker` compose stack (core: postgres/redis/migrate/app; profiles: oidc/obs/graph/bus/objects), multi-stage non-root `Dockerfile.app`, Keycloak dev realm (confidential client, PKCE S256, password grant off), Prometheus config, `.dockerignore`, `Makefile`, `/metrics` route, 49 integration tests and 15 offline deployment-config checks. Verified: **pytest 158 passed / 49 skipped**, mypy --strict clean (67 files), ruff clean. **Docker not installed — no image built, no container started, zero integration tests executed.** |
| 2026-09-08 | 1 (Unit 4) | `services/api-gateway`: app factory + hardening stack, `/healthz` `/readyz` `/health/deps` `/api/v1/meta`, Redis-backed sessions + CSRF double-submit, `get_principal` (privileges re-resolved per request), deny-by-default `require_permission` with metered + audited denials, tenant-scoped repositories, Argon2id local login with lockout and no enumeration/timing oracle, OIDC authorization-code + PKCE + state + nonce with no auto-provisioning, `/me`, audited admin user/role routes, explicit ORM→contract mappers. Verified: **pytest 143 passed**, mypy --strict clean (66 files), ruff clean. **No real Postgres/Redis/OIDC yet.** |
| 2026-09-08 | 1 (Unit 3) | `sm_common.db.base`/`models` (8 Phase-1 tables, UUIDv7 PKs, enum CHECKs rendered from `sm_contracts`, role partial unique indexes, security state kept out of contracts); `sm_common.audit.writer.AuditWriter` (per-tenant advisory lock, hash chain, runs in caller's transaction); `migrations/postgres` (alembic.ini + async env.py + `0001_initial` with `updated_at` and append-only audit triggers + `0002_seed_rbac` with 14 permissions / 5 system roles / grants, uuid5-derived ids). Verified: **pytest 102 passed**, mypy --strict clean (30 files), ruff clean, `alembic upgrade head --sql` emits full DDL offline. **Migrations never applied to a real database** (no Docker). Dep added: alembic 1.19.2. |
