# Observability

Complements `event-model.md` and ADR-014/ADR-020. Every service exposes
`/metrics` (Prometheus, unauthenticated — network-policy gated), `/healthz`
(liveness), `/readyz` (readiness — 503 when a required dependency is down). No
metric value is ever synthesized; counters move only on real activity.

## Metric catalog

Every metric carries a `service` label.

### HTTP (all services with an HTTP surface)

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `sm_http_requests_total` | counter | method, path, status | requests handled |
| `sm_http_request_duration_seconds` | histogram | method, path | latency |
| `sm_dependency_up` | gauge | dependency | 1 if reachable at the last readiness check |

### Auth / rate limiting (api-gateway, ingestion-gateway)

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `sm_authn_failures_total` | counter | reason | authentication failures |
| `sm_authz_denials_total` | counter | permission | authorization denials |
| `sm_audit_write_failures_total` | counter | action | audit rows that could not be written — **any non-zero value is a gap in the trail** |
| `sm_rate_limited_total` | counter | — | requests rejected 429 |
| `sm_rate_limiter_errors_total` | counter | — | limiter-store failures (api-gateway fails open; ingestion fails closed) |

### Event bus (`sm_common.bus`, every producer / consumer)

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `sm_producer_send_errors_total` | counter | topic | sends that raised after the client's own retries |
| `sm_consumer_records_total` | counter | group, topic | records handled |
| `sm_consumer_retries_total` | counter | group | in-process handler retries before success or DLQ |
| `sm_consumer_dlq_total` | counter | group, reason (`poison` \| `retries_exhausted`) | records dead-lettered |
| `sm_consumer_lag` | gauge | group, topic, partition | records behind the high-watermark at the last poll |

### Ingestion (`ingestion-gateway`)

`sm_ingest_accepted_total{source_type}`, `sm_ingest_rejected_total{source_type}`,
`sm_ingest_duplicates_total{source_type}`, `sm_ingest_dedup_errors_total`,
`sm_ingest_sink_errors_total{sink}` (`raw` \| `dlq`).

### Normalization (`normalization-engine`)

`sm_normalize_in_total{source_type}`, `sm_normalize_out_total{source_type}`.
DLQ / retry / produce-error counts are the shared `sm_consumer_*` /
`sm_producer_*` metrics (`group="normalization"`).

### Stream processing (`stream-processor`)

`sm_stream_in_total{kind}`, `sm_stream_commands_out_total{op}`.

## Alerts

| Alert | Condition | Why |
|---|---|---|
| **DLQ depth** | `sum(sm_consumer_dlq_total) - sum(sm_consumer_dlq_total offset 1h) > 0` sustained, or the `<topic>.dlq` topic's message count rising | poison / persistently-failing records are piling up — paged (event-model.md §5) |
| **Consumer lag** | `sm_consumer_lag > <threshold>` for `> 10m` per `group` | a consumer cannot keep up — scale it or investigate a slow handler |
| **Audit-write gap** | `increase(sm_audit_write_failures_total[5m]) > 0` | the audit trail has a hole — investigate immediately |
| **Rate-limiter store down** | `increase(sm_rate_limiter_errors_total[5m]) > 0` | Redis outage — ingestion is now rejecting (fail-closed) or the API is unprotected (fail-open) |
| **Producer send errors** | `increase(sm_producer_send_errors_total[5m]) > 0` | the bus is unreachable from a producer — upstream requests are failing 503 |
| **Readiness flapping** | `sm_dependency_up == 0` | a required dependency is down; the orchestrator has stopped routing to this instance |

## Tracing

W3C trace-context (`traceparent`) is honoured at every HTTP boundary and the
`correlation_id` is carried on every event envelope end to end, so a sensor POST
can be followed through `telemetry.raw` → `events.canonical` → `graph.commands`.
OTLP export is opt-in (`SM_OTEL_EXPORTER_OTLP_ENDPOINT`); no collector is wired
locally yet.
