# Event model

Authoritative for the durable event bus (Kafka). Complements ADR-018.

## 1. Canonical envelope

Defined once in `packages/contracts-py` as `EventEnvelope[PayloadT]`. Fields:
`event_id` (UUIDv7), `event_type` (enum string), `event_version` (int),
`occurred_at` (RFC3339 UTC), `ingested_at` (RFC3339 UTC), `producer`
(`<service>@<semver>`), `tenant_id` (UUID), `source`
(`{type, sensor_id?, site?}`), `correlation_id` (UUID), `trace_id` (W3C),
`partition_key` (string), `payload` (typed), `metadata` (object).

Rules:

- `event_id` is the global idempotency key. A consumer that has processed an
  `event_id` must not re-apply its side effects (dedup set in Redis + natural
  idempotency in the sink).
- `partition_key` = `sha256(tenant_id + ':' + primary_entity)[:16]`. Ordering is
  guaranteed **only** within one partition. Cross-partition/global ordering is
  never assumed.
- `occurred_at` may be older than `ingested_at` (late/buffered sensor data).
  Stream jobs use event-time with bounded lateness; the API read models use
  `ingested_at` for "recent" queries.
- `tenant_id` on a produced event is set from the **authenticated producer
  context**, never copied from an untrusted inbound field.

## 2. Serialization & schema

- **MVP:** JSON, validated against JSON Schema generated from the Pydantic
  models. Producer validates before publish; consumer validates on receive;
  invalid → DLQ (never silently dropped, never partially processed).
- **Compatibility:** payload schema changes are **backward-compatible within a
  major `event_version`** (add optional fields only). A breaking change bumps
  `event_type` suffix (`...v1` → `...v2`) and both run in parallel during
  migration.
- **Later option U-004:** schema registry + Avro/Protobuf when volume/perf
  justifies; the envelope contract is designed to survive that change.

## 3. Topic catalog

| Topic | Partitions (initial) | Key | Retention | Cleanup | Producers | Consumer groups |
|---|---|---|---|---|---|---|
| `telemetry.raw` | 12 | tenant+sensor | 7d | delete | ingestion-gateway | `normalization` |
| `events.canonical` | 24 | tenant+entity | 30d | delete | normalization-engine | `stream-processor`, `graph-writer`, `detection`, `memory`, `api-projection` |
| `graph.commands` | 12 | tenant+entity | 7d | delete | stream-processor, detection-engine | `graph-writer` |
| `graph.events` | 12 | tenant+entity | 7d | delete | graph-service | `api-projection`, `notification-fanout` |
| `detections` | 12 | tenant | 90d | delete | detection-engine | `api-projection`, `ai-analyst`, `agent-orchestrator`, `memory`, `reporting`, `notification-fanout` |
| `attack_chains` | 6 | tenant | 180d | delete | stream-processor, detection-engine | `graph-writer`, `ai-analyst`, `memory`, `reporting` |
| `ti.updates` | 3 | source | 30d | compact | threat-intel-service | `normalization`, `detection` |
| `agent.tasks` | 6 | tenant | 30d | delete | agent-orchestrator, ai-analyst-service | `agent-workers` |
| `response.actions` | 6 | tenant | 365d | delete | agent-orchestrator | `audit-sink`, `api-projection` |
| `campaign.updates` | 3 | tenant | 180d | delete | memory-service | `ai-analyst`, `reporting` |
| `report.generated` | 3 | tenant | 90d | delete | reporting-service | `api-projection`, `notification-fanout` |
| `user.events` | 3 | tenant | 90d | compact | api-gateway | `audit-sink` |
| `<topic>.dlq` | = source | original | 30d | delete | any consumer | `dlq-ops` |

Partition counts are starting points; scale by adding partitions (never
reducing) with awareness that `partition_key` distribution changes.

## 4. Delivery semantics

- **At-least-once** end to end. **Exactly-once is not claimed anywhere.**
- Consumers commit offsets **after** side effects succeed (or after DLQ-ing).
- Idempotency mechanisms per consumer:
  - `graph-writer`: `command_id` uniqueness + MERGE semantics in Cypher.
  - `detection`: `(tenant_id, event_id, detector_version)` unique row.
  - `api-projection`: upsert by natural key; projections are rebuildable.
  - `memory`: dedup by `event_id` set.
- **Out-of-order:** stream jobs use watermarks + allowed lateness (default 5 min,
  configurable per job); events later than that go to a `*.late` side output for
  batch reconciliation.
- **Retry:** transient consumer error → in-process retry with exponential
  backoff (max 3), then DLQ. Producer error → retry with idempotent producer
  config; on persistent failure the producing request fails (fail-closed for
  ingestion).

## 5. DLQ handling

- **Consumer-side** (a stream job could not process a record): the DLQ message
  wraps the original + `{error_type, error_detail, consumer_group, failed_at,
  attempts}` — `sm_common.bus.dlq_payload`. Implemented by `normalization-engine`
  (Phase 2 Unit 4).
- **Producer-side reject at a trust boundary** (`ingestion-gateway`: a sensor
  sent malformed bytes that never became a valid event): the DLQ message is the
  **raw bytes verbatim**, with `reason` / `source_type` / `sensor_id` in Kafka
  headers, so `dlq-ops` sees exactly what the sensor sent. No `consumer_group` /
  `attempts` — there was no consumer.
- `dlq-ops` tooling: inspect, fix-and-replay to source, or discard (audited).
- DLQ depth is a paged alert.

## 6. Replay

- Replay = reset a consumer group's offsets to a timestamp and reprocess.
- Safe for idempotent consumers (`graph-writer`, `api-projection`, `memory`).
- **Not** safe to replay into `response.actions` consumers — replay of
  `detections` must target a dedicated `*-replay` consumer group that has
  side-effecting adapters disabled.
- Temporal reconstruction (req 12) and knowledge-graph rebuild use replay of
  `events.canonical` + `attack_chains`.

## 7. Stream-processing contracts (engine-independent — ADR-010)

| Job | Input | Output | State | Semantics |
|---|---|---|---|---|
| `feature-aggregator` | `events.canonical` | `features.derived` | keyed windows (per entity, sliding 5m/1h/24h) | event-time, 5m lateness |
| `attack-chain-correlator` | `events.canonical`, `detections` | `attack_chains` | keyed session state per tenant+entity | event-time, 10m lateness, session gap 30m |
| `lateral-movement` | `events.canonical` (auth + flow) | `graph.commands` (`USED_CREDENTIAL_ON`), `detections` (candidates) | keyed state per identity | event-time |
| `temporal-stitcher` | `events.canonical` | `events.canonical` (enriched `correlation_id`) or `identity.links` | keyed state per identity/session | event-time, 1h lateness |
| `graph-update-emitter` | `events.canonical` | `graph.commands` | minimal (dedup) | at-least-once + idempotent commands |

If the engine changes (Flink → Bytewax/Kafka Streams), these input/output topics
and semantics do not change.
