# sm-common

SentinelMesh shared **platform primitives**. No business logic, no domain
models (those are `sm-contracts`). Every service imports this.

## What's here (Phase 1, Unit 1)

| Module | Purpose |
|---|---|
| `config` | `AppSettings` — typed, `SM_`-prefixed env config, validated at startup (fail-fast; production guards reject CORS `*`, insecure cookies, missing secrets, `response_mode=auto` outside a policied production). `load_settings()` is cached. |
| `logging` | structlog JSON pipeline; injects `request_id`/`correlation_id`/`service`/`env`; runs every record through secret redaction. |
| `redaction` | `redact()` — key-based + pattern-based secret masking (passwords, bearer tokens, DSN passwords, JWTs). Used by logging and error serialization. |
| `context` | `request_id` / `correlation_id` `contextvars` + `request_context()` helper. |
| `ids` | `uuid7()` (RFC 9562 v7, time-ordered) for 3.11; `new_request_id`, `new_correlation_id`. |
| `clock` | `utcnow()` — the single time source. |
| `errors` | `SmError` hierarchy → canonical `sm_contracts.ErrorResponse` with correct HTTP status; messages redacted. |
| `security.passwords` | Argon2id `hash_password` / `verify_password` (+ rehash flag) / `dummy_verify` (constant-time for unknown users). |
| `security.jwt_internal` | Mint/verify short-lived audience-scoped service-to-service JWTs; key rotation. |
| `observability.health` | `liveness()`, `DependencyCheck`, `evaluate_readiness()` (bounded, concurrent) → canonical `HealthResponse` / `ReadyResponse`. |
| `fastapi` | `RequestContextMiddleware` (request/correlation IDs, access log), `install_exception_handlers` (canonical errors, no leaks), `SecurityHeadersMiddleware`, `BodySizeLimitMiddleware`, `build_cors_kwargs` (prod wildcard rejected). |

## Not here yet (Phase 1, Unit 2)

Live infrastructure clients: Postgres async engine / session / transaction
helpers, Redis client, OIDC client, OpenTelemetry exporter wiring, the
append-only audit-log writer.

## Dev

```
pip install -e "packages/contracts-py[dev]" -e "packages/common-py[dev]"
pytest packages/common-py
mypy --strict packages/common-py/src/sm_common
ruff check packages/common-py
```
