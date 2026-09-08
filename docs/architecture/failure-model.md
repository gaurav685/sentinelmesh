# Failure model

Constitution §17. Principle: **fail safely, never silently swallow, never
fabricate a result.** Every degradation is observable (metric + structured log)
and, where it affects correctness, surfaced in the API response as an explicit
`degraded` marker.

Legend: **DL** = data-loss risk.

| Failure | Detection | Behavior | Retry | Fallback / degradation | Recovery | DL |
|---|---|---|---|---|---|---|
| **PostgreSQL unavailable** | pool acquire error / healthcheck | request path returns `503` w/ `Retry-After`; consumers pause (no offset commit) | driver retry (bounded) + circuit breaker | read APIs may serve from `detection_read`/Redis cache with `degraded=true` if cache fresh | auto on reconnect; consumers resume from last committed offset | none (offsets uncommitted) |
| **Kafka unavailable** | producer/consumer errors | ingestion returns `503` (fail-closed) → sensors buffer; internal producers buffer bounded in-memory then fail the operation | idempotent producer retry | none for ingestion; internal ops fail cleanly | auto on broker recovery | none if sensors buffer; **DL if sensor buffer overflows** (sensor-side concern, documented to customers) |
| **Redis unavailable** | client error / healthcheck | sessions fail → re-auth; rate-limit: ingestion fail-closed, read-API fail-open + alert; dedup: consumers fall back to sink-level idempotency; fan-out: WS pauses, clients poll | client retry | caches recompute on demand | auto; caches warm over time | none (all Redis data rebuildable) |
| **Neo4j unavailable** | driver error / healthcheck | `graph-service` query API `503`; `graph-writer` consumer pauses (lag grows, alarmed) | driver retry + breaker | UI graph panel shows "graph temporarily unavailable"; detections still flow (graph context contribution marked missing) | auto; writer replays `graph.commands` from last offset | none |
| **Flink / stream-processor down** | job manager / lag metric | jobs restart from last checkpoint | Flink restart strategy (exponential, capped) | derived features/chains delayed; `detection-engine` marks feature inputs `STALE` | checkpoint restore; at-least-once downstream (idempotent sinks) | none (checkpointed) |
| **ML model unavailable** (load fail / timeout) | `ml-inference` readiness / call error | `detection-engine` sets `scoring_status=DEGRADED`, uses statistical fallback score, emits `ml_degraded` metric | per-call retry once | rule/statistical scoring; detection still emitted, flagged | model reload on new version or restart | none |
| **LLM provider unavailable** | adapter timeout / 5xx / 429 | typed `LLM_UNAVAILABLE` to caller; **no fabricated text**; analyst UI shows "AI explanation unavailable" | backoff retry (bounded), then fail | deterministic non-LLM summary (template from evidence) where one exists | auto | none |
| **External TI provider unavailable** | adapter timeout / error | serve cached reputation, mark `freshness=STALE`; enrichment continues with `ti_enrichment=PARTIAL/SKIPPED` | scheduled re-poll | cache; never block the pipeline; never fabricate an IOC verdict | auto on next successful poll | none |
| **Malformed telemetry** | envelope/payload schema validation | → `telemetry.raw.dlq` with reason; `ingest_reject` metric++ | none (deterministic) | rest of the batch/stream unaffected | `dlq-ops` fix-and-replay or discard (audited) | none (in DLQ) |
| **Duplicate event** | `event_id` dedup set / unique constraint | side effects skipped (idempotent) | n/a | n/a | n/a | none |
| **Out-of-order event** | watermark vs `occurred_at` | processed if within allowed lateness; else → `*.late` side output | n/a | batch reconciliation job merges late events | scheduled reconciliation | none |
| **Consumer lag / slow consumer** | lag metric threshold | alert; autoscale consumer group (prod) | n/a | backpressure to upstream; ingestion stays fail-closed if `telemetry.raw` retention is threatened | scale out; lag drains | **DL only if lag exceeds retention** (alerted well before) |
| **Service crash** | liveness probe / orchestrator | pod restarted; in-flight sync requests fail with `503` (client retries); consumer rebalances | client + orchestrator | monolith profile: one crash affects grouped services (accepted for dev) | restart; resume from offsets | none |
| **Network partition** | timeouts, breaker open | each side degrades independently per rows above; no split-brain writes (single-writer per store) | breaker half-open probes | reads may be stale (`degraded=true`) | heal on reconnect | none |
| **DB transaction failure / deadlock** | exception | transaction rolled back; operation returns `409`/`503` as appropriate | bounded retry with jitter for deadlocks | none | n/a | none (atomic) |
| **Dependency timeout** | per-call deadline | typed error; partial response with `degraded` list of missing inputs | one retry for idempotent GETs | compute with available inputs, mark which were missing | n/a | none |
| **Invalid schema (internal event)** | consumer-side validation | → `<topic>.dlq`; alert (this is a bug, not bad input) | none | consumer continues with next message | fix producer, replay DLQ | none |
| **Poisoned / adversarial model input** | input range/shape validation + drift monitor | reject out-of-distribution inputs to a bounded score, flag `input_anomaly`; never crash the scorer | n/a | statistical fallback | investigate; retrain/robustify | none |
| **Malicious LLM prompt (injection)** | injection heuristics + output validation | refuse; audit with the offending context; `injection_detected` metric++ | n/a | deterministic path only | tune heuristics | none |
| **Unauthorized response action** | policy + authz check | action `DENIED`, audited; no target contacted | n/a | analyst notified; manual path | policy review | none |
| **api-gateway downstream service down** | per-call breaker | assemble response from available services; mark absent sections `degraded`; correct HTTP status (200 with degraded markers for partial reads, 503 only if nothing usable) | one retry | cached projections where available | auto | none |
| **Audit-write failure** | write error | for response actions: whole action transaction rolls back (action does not happen without its audit); for lower-severity: action proceeds, `audit_write_failed` metric++ + error log + retry queue | retry queue | n/a | replay retry queue | **audit gap risk** for non-critical events (metered, alerted) |
| **Object store (S3/MinIO) unavailable** | client error | report/model/checkpoint writes fail cleanly (`report.status=FAILED`, retryable); Flink checkpoint failure triggers job restart-from-previous | client retry | n/a | auto | none (retryable) |

## Startup failure (fail-fast — Constitution §18)

Every service validates its typed configuration at startup. A missing
`[required]` value, an unreachable `[required]` dependency at readiness, a
production config with a CORS wildcard, or `SM_RESPONSE_MODE=auto` without policy
→ the service **refuses to start** (non-zero exit, clear message, no secret in
the message).

## Shutdown (graceful — Constitution §11, §15)

On SIGTERM: stop accepting new work → drain in-flight HTTP (bounded grace) →
commit consumer offsets → close Kafka/DB/Neo4j/Redis clients → flush logs/traces
→ exit. Background tasks are supervised and cancelled with cleanup.
