# ingestion-gateway

Authenticated intake for sensor telemetry (R1). A sensor sends the **bare
payload**; the gateway authenticates the sensor, validates the payload against
the `sm_contracts.telemetry` schema, builds the canonical `EventEnvelope`
server-side, and hands the result to the raw-event sink (a malformed body goes
to the dead-letter sink instead — nothing is silently dropped).

## Endpoints (Phase 2)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/healthz` | none | liveness |
| GET | `/readyz` | none | 503 when Postgres or Redis is down |
| GET | `/api/v1/meta` | none | build info |
| GET | `/metrics` | none (network policy) | Prometheus exposition |
| POST | `/api/v1/ingest/{source_type}` | sensor | one payload; `source_type` ∈ `network_flow`, `auth_event`, `dns_query`, `process_exec`, `file_access` |
| POST | `/api/v1/ingest/batch` | sensor | `{source_type, events: [...]}`, up to `SM_INGEST_BATCH_MAX_EVENTS` |

`202` on accept (`200` when suppressed as a duplicate `X-Sensor-Event-Id`),
`404` for an unknown `source_type`, `422` (+ DLQ) for bad JSON or a failed
payload schema, `401` for any sensor-auth failure, `413` over
`SM_HTTP_MAX_BODY_BYTES`, `503` when the rate limiter's store is unavailable.

## Security properties

- **Sensor auth:** `Authorization: <sensor_id>.<secret>` (an optional `Bearer `
  prefix is accepted). Argon2id verify against `sensor.credential_hash`;
  `dummy_verify` for an unknown/malformed id so there is no timing oracle; the
  secret is checked before the `status`/`deleted_at` gate. Every failure is one
  generic `401 unauthenticated`.
- **Tenant is never taken from the body.** `tenant_id`, `source.sensor_id` and
  `source.type` on the envelope come only from the authenticated
  `SensorIdentity`. The payload models are `extra="forbid"`, so a sensor cannot
  even send a `tenant_id` field.
- **Rate limiter fails closed.** Unlike the api-gateway, a limiter-store outage
  rejects (`503`) rather than letting an unbounded flood through.
- **Idempotency:** an optional `X-Sensor-Event-Id` is remembered in Redis for
  `SM_INGEST_DEDUP_TTL_SECONDS`; a retry with the same id returns `200` and is
  not re-sinked. A Redis outage does not reject — downstream is idempotent on
  `event_id` anyway.
- No interactive docs (`/docs`, `/openapi.json`) in production.

## Sinks

`RawEventSink` / `DeadLetterSink` are interfaces with two implementations:

- `SM_EVENT_BUS_ENABLED=true` — `KafkaRawEventSink` → `telemetry.raw` (canonical
  JSON, keyed on `partition_key`), `KafkaDeadLetterSink` → `telemetry.raw.dlq`
  (raw body, `reason`/`source_type`/`sensor_id` headers). aiokafka producer,
  idempotent, `acks=all`. `/readyz` probes it. **Mandatory in production.**
- otherwise — `LoggingRawEventSink` / `LoggingDeadLetterSink` (dev, tests).

A `telemetry.raw` produce failure fails the request with `503`
(`sm_ingest_sink_errors_total{sink=raw}`); the sensor retries and the idempotent
producer prevents partition duplicates. A DLQ produce failure is swallowed and
metered (`{sink=dlq}`) so it cannot turn a client `4xx` into a `5xx`.

## Run locally

```
pip install -e "packages/contracts-py[dev]" -e "packages/common-py[dev]" -e "services/ingestion-gateway[dev]"
python -m sm_ingestion_gateway   # port 8001; needs Postgres + Redis
```

## Test

```
pytest services/ingestion-gateway    # in-memory fakes; no Docker needed
```

The unit tests build the real app and replace only sensor auth, Redis and the
sinks. `SensorAuth` against real SQL is `tests/integration/test_sensor_auth_pg.py`.
