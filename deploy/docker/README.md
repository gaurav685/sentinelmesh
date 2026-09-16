# Local infrastructure (docker-compose)

Everything here is for **local development and CI**. Production deployment is
Helm/Kubernetes — see `docs/architecture/deployment.md`.

**Status: authored, not executed.** Docker is not installed on the development
machine, so no image has been built and no container has been started. Nothing in
this directory has been verified at runtime. `docs/IMPLEMENTATION_STATE.md`
records exactly which checks remain outstanding.

## Prerequisites

- Docker Desktop (or Docker Engine + the compose plugin)
- a `.env` at the repository root, copied from `.env.example`, with at least:
  - `SM_PG_PASSWORD`
  - `SM_INTERNAL_JWT_SIGNING_KEY`
  - `SM_OIDC_CLIENT_SECRET`
  - `SM_S3_SECRET_ACCESS_KEY` (only needed for the `objects` profile)

Compose refuses to start if `SM_PG_PASSWORD` is unset — a database is never
brought up without a password.

## Start the core stack

```
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

That is `postgres`, `redis`, `migrate` and `app`. `migrate` runs
`alembic upgrade head` and exits; `app` will not start until it succeeds, so the
service never runs against an older schema.

| Service | Host port | Purpose |
|---|---|---|
| `postgres` | 5432 | relational store |
| `redis` | 6379 | sessions, cache, rate limits |
| `app` | 8000 | api-gateway |

Check it:

```
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
curl http://localhost:8000/api/v1/meta
```

## Optional profiles

```
docker compose -f deploy/docker/docker-compose.yml --profile oidc    up -d   # keycloak      :8080
docker compose -f deploy/docker/docker-compose.yml --profile obs     up -d   # prometheus    :9090, grafana :3001
docker compose -f deploy/docker/docker-compose.yml --profile graph   up -d   # neo4j         :7474/:7687  (Phase 3+)
docker compose -f deploy/docker/docker-compose.yml --profile bus     up -d   # redpanda      :9092        (Phase 2+)
docker compose -f deploy/docker/docker-compose.yml --profile objects up -d   # minio         :9000/:9001  (Phase 5+)
```

## Networking rule

Inside the compose network, services address each other by **service name**:
`postgres`, `redis`, `keycloak`, `neo4j`, `redpanda`, `minio`. `localhost` inside
a container is that container. The `environment:` blocks in the compose file
override the host-facing values from `.env` for exactly this reason, so the same
`.env` works both inside Docker and when running the app on the host.

`tests/contract/test_deploy_local_config.py` asserts this offline.

## Integration tests

The tests in `tests/integration/` connect from the **host** to the published
ports, so `localhost` is correct there. They skip with an actionable message
when the services are unreachable.

```
docker compose -f deploy/docker/docker-compose.yml up -d postgres redis
docker exec sentinelmesh-postgres-1 psql -U sentinelmesh -c "CREATE DATABASE sentinelmesh_test;"  # once
docker exec sentinelmesh-postgres-1 psql -U sentinelmesh sentinelmesh_test -c "CREATE EXTENSION vector;"  # once
pytest tests/integration -q -m integration
```

The `CREATE DATABASE` step matters: these tests drop/recreate/truncate real
tables against `SM_TEST_PG_DB` (default `sentinelmesh_test`, deliberately
not the same database `SM_PG_DB` points your running stack's `app` at) --
pointing `SM_TEST_PG_DB` at your real `sentinelmesh` database will destroy
its schema, as running this suite actually did during Phase 18.

They cover: migrations `upgrade head` → `downgrade base` → `upgrade head`, seed
content and idempotency, triggers and partial indexes, `AuditWriter` chain
linearity under concurrent appends, the append-only audit trigger, schema
constraints, the SQL repositories' tenant scoping and pagination, and the Redis
session/OIDC-state TTL semantics.

## The Keycloak dev realm

`keycloak/realm-sentinelmesh.json` is imported on start (`--import-realm`). It
defines the `sentinelmesh` realm, the confidential `sentinelmesh-api` client
(PKCE S256, password grant disabled) and one test user.

The client secret and the user password in that file are **development
placeholders committed on purpose**. They are valid only for this local realm.
Never reuse them, and never point a non-local `SM_OIDC_ISSUER` at this realm.

## Data

Named volumes `postgres-data`, `neo4j-data`, `minio-data`. `make down` (or
`docker compose ... down -v`) deletes them. Redis runs with persistence off —
its contents are disposable by design.
