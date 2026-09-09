# normalization-engine

Raw telemetry → canonical events (R2). A pure stream processor: consumes
`telemetry.raw`, maps each sensor payload to a `CanonicalEventPayload`, and
produces `events.canonical`. No HTTP ingest surface — only `/healthz`,
`/readyz`, `/api/v1/meta`, `/metrics`.

## Pipeline

`telemetry.raw` record → parse `EventEnvelope[<telemetry payload>]` → per-source
mapper → `CanonicalEventPayload` → enrichers (none yet) →
`EventEnvelope[CanonicalEventPayload]` → `events.canonical`.

- **Server-set on the canonical envelope:** new `event_id`; `event_type =
  event.canonical`; `producer = normalization-engine@<version>`;
  `tenant_id` / `source` / `correlation_id` / `trace_id` copied from the source
  event; `occurred_at` = the source event time; `partition_key =
  sha256(<tenant_id>:<actor|target|first entity>)[:16]`;
  `metadata.raw_event_id` = the source `event_id`. The payload keeps
  `raw_event_id` / `raw_event_type` lineage.
- **Deterministic mapping only.** Geo-IP, hostname resolution, identity
  stitching and threat-intel tagging are `enrich.Enricher` providers; the
  default list is empty so `enrichment` stays `{}`.

## Delivery semantics (event-model.md §4/§5)

- At-least-once. `EventBusConsumer` commits offsets only after every record in a
  poll batch is handled or dead-lettered. Handlers are idempotent-safe: the
  canonical producer is idempotent (`acks=all`).
- **Poison record** (bad JSON, unknown `event_type`, invalid envelope, mapper
  failure) → `telemetry.raw.dlq` wrapping the original +
  `{error_type, error_detail, consumer_group, attempts, failed_at}`; the offset
  commits and the partition keeps moving.
- **Produce failure** (canonical or DLQ topic unreachable) → retry with backoff
  (3 attempts); still failing → the batch is not committed and is redelivered.
  `/readyz` goes 503 while the broker is down.

Consumer group: `SM_KAFKA_CONSUMER_GROUP` (default `normalization`).

## Run locally

```
pip install -e "packages/contracts-py[dev]" -e "packages/common-py[dev]" -e "services/normalization-engine[dev]"
python -m sm_normalization_engine   # port 8002; needs Kafka (docker compose --profile bus up -d redpanda)
```

## Test

```
pytest services/normalization-engine    # mappers + engine handler with a fake producer; no broker
```

`tests/integration/test_normalization_bus.py` runs the full loop against real
Redpanda.
