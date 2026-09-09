# SentinelMesh — Implementation State

**This file is authoritative for "where we are" and "what to do next".**
Update it at the end of every coherent implementation unit.

---

## Current phase

**Phase 5 — Detection + Anomaly Detection. IN PROGRESS — Unit 1 DONE (contracts +
schema).** Unit 1: `sm_contracts` detection domain (`DetectionPayload` on the
`detections` topic + `EventType.detection_raised`, `EvidenceItem` / `EvidenceKind`,
`detection_dedup_key` / `detection_id_for`, the `Detection` / `Anomaly` /
`ThreatScore` / `SecurityAlert` DTOs, the `Severity` / `DetectorKind` /
`AnomalyMethod` / `ScoringStatus` / `DetectionStatus` / `AlertStatus` /
`ThreatSubjectType` enums), the SQLAlchemy models + Alembic migration `0003`
(`detection`, `anomaly`, `threat_score`, `security_alert` — the `detection-engine`
system of record). Units 2–5 (the `sm_ml` feature/model layer, `ml-inference`,
`detection-engine`, wiring + e2e + exit report) follow.

**Phase 4 — Neo4j + Graph Intelligence Foundation. COMPLETE / CI-VERIFIED.**
Units 1–4, all four CI jobs green on a clean runner: runs
[`34346140544`](https://github.com/gaurav685/sentinelmesh/actions/runs/34346140544)
/ [`34348143536`](https://github.com/gaurav685/sentinelmesh/actions/runs/34348143536)
/ [`34349655012`](https://github.com/gaurav685/sentinelmesh/actions/runs/34349655012)
/ [`34350607501`](https://github.com/gaurav685/sentinelmesh/actions/runs/34350607501)
(`integration` runs against real PostgreSQL + Redis + Redpanda + Neo4j 5). Write
path `graph.commands → graph-service → Neo4j`, read path `GraphRepository` +
`/api/v1/graph/*`, end-to-end from `events.canonical` verified. Phase 4 exit
report + §23 review below.
Unit 1 (run `34346140544`):
the Neo4j async driver wrapper, the label/relationship allowlist (Cypher-injection
guard), the versioned `.cypher` schema migration + runner, the production config
guard, and the compose/CI wiring for a Neo4j service. Unit 2 (local + integration
verified, CI pending): `services/graph-service` — the only write path into Neo4j;
consumes `graph.commands`, applies each as a parameterized idempotent MERGE,
emits `graph.events`. Units 3–4 (the graph-query API, the full integration set +
exit report) follow.

**Phase 3 — Kafka + Stream Processing. COMPLETE / CI-VERIFIED.** Units 1–4:
Unit 1 topic registry; Unit 2 bus hardening + topic provisioning; Unit 3
`RecordProcessor` + `stream-processor` (`graph-update-emitter`); Unit 4 ADR-010
decision (U-001/U-002 **resolved** — plain-Python for stateless, cluster engine
deferred per job), `scripts/replay.py`, `docs/architecture/observability.md`,
`REQUIREMENTS_TRACEABILITY` R3/R20, the Phase 3 exit report (below). **CI green
on a clean runner** (run
[`34342866073`](https://github.com/gaurav685/sentinelmesh/actions/runs/34342866073)).
Flink **not** implemented — no JDK 11+ locally (ADR-001), no stateful job's
consuming phase has arrived.

---

### Phase 4, Unit 2 — graph-service (the Neo4j write path) (DONE — local + integration verified)

- `services/graph-service` (port 8004, module `sm_graph_service`, consumer group
  `graph-writer`). Mirrors the `stream-processor` shape: a Kafka consumer with a
  health/metrics HTTP surface, no ingest. The lifespan owns the Neo4j driver, the
  producer, the consumer, and one `EventBusConsumer.run(RecordProcessor)` task.
- `GraphWriter.apply(GraphCommandPayload) -> MutationResult`:
  - **Parameterized Cypher only.** The single thing interpolated is a node label
    / relationship type, and only after `normalize_label` + membership check
    against `sm_contracts.GRAPH_NODE_LABELS` / `GRAPH_REL_TYPES`. Off-list → the
    engine raises `PoisonError` → `graph.commands.dlq`.
  - **Idempotent by `command_id`** — a read of the `_GraphCommand` ledger
    short-circuits a redelivery to `DUPLICATE` (no mutation). The ledger row is
    written *after* the (idempotent) MERGE, so a crash between the two just
    re-runs the MERGE on retry.
  - **Node key** must be exactly `{<key prop for label>: value}`; MERGE is keyed
    on the synthetic `graph_node_uid(tenant_id, value)` (`"<tenant>:<value>"`).
  - **Out-of-order safe** — every node/rel carries `_watermark` (newest
    `observed_at` applied). An older command widens `first_seen` / `last_seen`
    but does not overwrite props → `STALE`.
  - **Tenant invariants by construction** — `tenant_id` written everywhere; node
    uid embeds the tenant, so an edge can only join same-tenant nodes.
  - **Missing endpoint nodes** for a `MERGE_EDGE` are created thin.
  - **`MERGE (s)-[r:REL]->(e)`** on endpoints only → repeated commands update the
    one edge, never duplicate it.
  - `PRUNE` → `PoisonError` (the retention job is later).
- `GraphEngine.handle`: parse the `graph.command` envelope (bad → `PoisonError`),
  apply, `GraphUnavailableError` → `TransientError` (retry, never drop), then
  produce one `graph.events` record (`event_id == command_id`); a failed produce
  → `TransientError`.
- Contracts: `EventType.graph_event` (`"graph.event"` → topic `graph.events`),
  `GraphEventPayload` (`command_id, op, outcome ∈ APPLIED|DUPLICATE|STALE,
  tenant_id, observed_at, raw_event_id, label, nodes_written,
  relationships_written`), `GraphMutationOutcome`. Registered; 2 new JSON Schemas
  (38 total). `gen_contracts.py --check` clean.
- Metric `sm_graph_commands_applied_total{service,op,outcome}` (retry/DLQ/lag are
  the shared bus metrics).
- Wiring: `graph-service` added to `Dockerfile.app` (COPY + `pip install`),
  `docker-compose.yml` (`graph` profile, `depends_on` neo4j healthy, port 8004),
  CI (`static`/`unit`/`integration` installs, `mypy` 7th tree, `image` import
  check). `pyproject.toml` `known-first-party` += `sm_graph_service`.
- Tests: `services/graph-service/tests` — `test_writer.py` (10, fake graph:
  allowlist rejection, key validation, prune, duplicate short-circuit,
  parameterization, stale, edge), `test_engine.py` (6: envelope parsing, error
  mapping, one `graph.events` per command), `test_health.py` (4).
  `tests/integration/test_graph_service_neo4j.py` (6, real Neo4j via the `graph`
  fixture): tenant-scoped node creation, `command_id` no-op, out-of-order keeps
  the newer value, edge creation + both endpoints, no duplicate relationship,
  cross-tenant isolation (two nodes, zero cross-tenant edges). CI-green (run
  `34348143536`).

### Phase 4, Unit 3 — the graph-query API (DONE — local + integration verified)

- `sm_graph_service.repository.GraphRepository` — read-only, tenant-scoped,
  bounded queries:
  - `entity(tenant_id, label, key)` — one node's public props, or `None`.
  - `neighbors(tenant_id, label, key, depth=1, limit=None)` — a bounded
    neighbourhood as `{nodes, edges, truncated}`. Two parameterized reads (nodes,
    relationships), each `LIMIT $cap`.
  - `attack_path(tenant_id, src, dst, max_depth=4)` — `shortestPath` between two
    keyed nodes, projected to primitive node/edge dicts.
  - **Parameterized only.** The only interpolated values are an allowlisted node
    label (`ValidationFailed` → 422 otherwise) and an integer traversal depth
    clamped to `[1, SM_NEO4J_TRAVERSAL_MAX_DEPTH]` (default cap 8). Every path is
    `WHERE all(x IN nodes(p) WHERE x.tenant_id = $tenant)`. Row cap
    `SM_NEO4J_QUERY_MAX_ROWS` (default 1000). `_`-prefixed props + `uid` stripped.
- `routes/graph.py` — `GET /api/v1/graph/{entity,neighbors,paths}` on
  `graph-service`. `deps.get_principal` verifies the internal service JWT
  (`verify_internal_token`, audience `graph-service`) — **the tenant scope is the
  token's `tenant_id`, never a query field**. Bad / missing / wrong-audience /
  wrong-key token → 401. Missing entity → 404.
- Config: `SM_NEO4J_QUERY_MAX_ROWS` (1000), `SM_NEO4J_TRAVERSAL_MAX_DEPTH` (8).
  `.env.example` updated.
- Response models (`EntityResponse` / `NeighborsResponse` / `PathResponse`) are
  DRAFT and service-local (`schemas.py`) until the read surface settles.
- Tests: `test_repository.py` (9 — label rejection, depth clamp up + floor, row
  cap + `truncated`, param-not-in-cypher, `_public` stripping, path projection),
  `test_graph_api.py` (8 — 401 matrix, tenant-from-token, 404, 422, view shape).
  `tests/integration/test_graph_service_neo4j.py` +4 (real Neo4j: public-props
  only, bounded neighbourhood at depth 1 vs 2, shortest path length 2,
  cross-tenant reads return nothing). CI-green (run `34349655012`).

**Phase 2 — Telemetry Ingestion + Normalization. COMPLETE / CI-VERIFIED.**
Units 1–4 implemented; §23 review done; full compose stack + live end-to-end
verified; **CI green on a clean runner** (run
[`34333269219`](https://github.com/gaurav685/sentinelmesh/actions/runs/34333269219),
2026-09-09): `static` (ruff + `mypy --strict`), `unit` (268 tests + schema
`--check`), `integration` (63 tests — real PostgreSQL 16 + Redis 7 + Redpanda,
`0001 -> 0002` migrations), `image` (build of all four services + non-root +
entrypoint imports + prod fail-fast guards). Pipeline: sensor →
`ingestion-gateway` → `telemetry.raw` → `normalization-engine` →
`events.canonical` (poison → `telemetry.raw.dlq`).

Phase 1 exited INTEGRATION VERIFIED on local Docker; its CI jobs also went green
in the same run.

### Phase 3, Unit 3 — RecordProcessor + stream-processor (graph-update-emitter) (DONE)

- `sm_common.bus.RecordProcessor` — the shared retry / DLQ policy
  (event-model.md §4/§5). A domain handler raises `PoisonError` (→ DLQ now) or
  `TransientError` (→ exp backoff × `SM_KAFKA_HANDLER_MAX_ATTEMPTS`, then DLQ);
  anything else propagates (uncommitted → the consumer rewinds + redelivers).
  DLQ record is `dlq_payload(...)` to `dlq_topic(record.topic)`; meters
  `sm_consumer_dlq_total` / `sm_consumer_retries_total`.
- `normalization-engine` refactored onto it: `engine.handle` now only *signals*
  intent (raises `PoisonError` / `TransientError`); the hand-rolled parse→DLQ
  and produce-retry loops are gone. `NormalizationMetrics` dropped its
  `sm_normalize_dlq_total` / `sm_normalize_produce_errors_total` (the shared bus
  metrics cover it — no duplication).
- `sm_contracts.graph` — `GraphCommandPayload` (CONTRACTS.md §5:
  `command_id, op ∈ MERGE_NODE|MERGE_EDGE|SET_PROPS|PRUNE, tenant_id,
  observed_at, raw_event_id, label, key, props, start/end`), `GraphOp`,
  `GraphEndpoint`, `graph_command_id(raw_event_id, op, label, discriminator)`
  (deterministic). Registered for `EventType.graph_command`; 2 new JSON Schemas.
- `services/stream-processor` (port 8003) — a stateless stream job with a
  health/metrics HTTP surface. `emitter.emit(canonical_envelope)` maps one
  `events.canonical` event → a `MERGE_NODE` command per entity + one
  `MERGE_EDGE` `actor -[REL]-> target` (`REL` from `CanonicalKind`,
  `data-model.md` vocab; `EntityKind` → Neo4j label). Each command's envelope
  `event_id == payload.command_id`, deterministic in the source canonical
  `event_id`, so a redelivery re-emits identical commands (idempotent for
  `graph-writer`, Phase 4). `StreamEngine.handle` wrapped by `RecordProcessor`;
  `events.canonical` → `graph.commands`, poison → `events.canonical.dlq`.
  Metrics `sm_stream_{in,commands_out}_total`.
- Added to `Dockerfile.app` (one image), compose (`bus` profile,
  `depends_on: topics-init`), Makefile, CI (install + `mypy` + image
  entrypoint-import check).
- `.env` `SM_KAFKA_BOOTSTRAP_SERVERS` corrected to `localhost:19092` (Redpanda
  EXTERNAL listener; matches `.env.example`).
- Tests: `services/stream-processor/tests` (15 — emitter mappings, engine
  DLQ/retry/redelivery, health); `tests/integration/test_stream_processor_bus.py`
  (2, real Redpanda — canonical → graph commands with the right shape; poison →
  DLQ + next good still processes). `test_normalization_bus.py` updated for the
  `RecordProcessor` refactor.
- Verified: pytest **293** non-integration / **74** integration
  (`SM_REQUIRE_INTEGRATION=1`, Redpanda v24.2.11 + Postgres 16 + Redis 7),
  `mypy --strict` clean (122 files), `ruff` clean, `gen_contracts --check` clean,
  `docker compose --profile bus config` valid.

### Phase 3, Unit 2 — bus hardening + topic provisioning (DONE)

- `sm_common.bus.admin.ensure_topics(settings, specs?)` — `AIOKafkaAdminClient`
  create-if-absent from the registry's partition counts + retention, **and
  grows** a pre-existing under-provisioned topic (`create_partitions`; Kafka
  allows increasing only). `scripts/provision_topics.py` CLI (`--list`),
  `make provision-topics` / `make topics`, a compose `topics-init` one-shot that
  `normalization-engine` now `depends_on: service_completed_successfully`.
- `EventBusConsumer`:
  - **at-least-once on handler failure** — `run_once` now *rewinds the fetch
    position* to the batch start on any exception, so the same consumer
    redelivers on the next poll (aiokafka advances the in-memory position on
    `getmany`; the old code only redelivered after a rebalance/restart). This
    was a real gap — `test_offset_is_committed_only_after_the_handler_succeeds`
    proves the fix.
  - **graceful shutdown** — `request_stop()` (flag) lets the in-flight batch
    finish + commit; `stop()` waits on the batch lock then closes. The
    `normalization-engine` lifespan drives it with `SM_KAFKA_SHUTDOWN_GRACE_MS`.
  - **backpressure** — `SM_KAFKA_MAX_POLL_RECORDS` bounds in-flight records; no
    prefetch of the next batch until the current one commits.
  - **replay** — `seek_by_timestamp(when)` on all assigned partitions
    (event-model.md §6).
  - **lag** — after each poll, `sm_consumer_lag{group,topic,partition}` =
    `highwater - position`; plus `sm_consumer_records_total`.
- `EventBusProducer`: `flush()` on `stop()`; `linger_ms` from settings; a
  fast-fail + `sm_producer_send_errors_total{topic}` on a send that raises.
- `Metrics` gained `consumer_records` / `consumer_dlq` / `consumer_retries` /
  `consumer_lag` / `producer_send_errors`. Config: `kafka_linger_ms`,
  `kafka_max_poll_records`, `kafka_shutdown_grace_ms`, `kafka_handler_max_attempts`.
- `normalization-engine` passes `metrics` into its producer + consumer.
- Tests: `tests/integration/test_bus_kafka.py` (9, real Redpanda) — topic
  provision + grow, produce/consume, JSON round-trip, offset-commit-after-
  side-effect, at-least-once redelivery, graceful shutdown commits the in-flight
  batch, replay by timestamp, lag/records metrics, producer send-error metric.
  Verified: pytest 278 non-integration / **72 integration**, `mypy --strict`
  clean (108 files), `ruff` clean, `gen_contracts --check` clean.

### Phase 3, Unit 1 — topic registry + versioned event types (DONE)

`sm_contracts.topics`: `TopicSpec` (name, partitions, key, retention, cleanup,
producers, consumer_groups, `has_dlq`, `partitions_min`, `retention_ms`) and
`TOPICS` — the 12-topic catalog from event-model.md §3, verbatim. `EVENT_TYPE_TOPIC`
maps every `EventType` to its topic (`topic_for_event_type`); `dlq_topic(t)` =
`<t>.dlq`; `replay_group(g)` = `<g>-replay` (event-model.md §5/§6).
`EVENT_TYPE_VERSION` records the major version per type (all 1 today; a breaking
change adds a `.v2` member — the "versioned event types" policy, now also in
event-model.md §2). `ingestion-gateway` / `normalization-engine` now derive their
topic names from the registry (no string literals). `test_topics.py` (10 tests)
guards the mapping, the catalog invariants and the key partition counts.
Verified: pytest 278 non-integration / 63 integration, mypy --strict clean, ruff
clean, `gen_contracts --check` clean.

### Phase 2, Unit 1 — telemetry payload contracts (DONE)

`sm_contracts.telemetry`: `NetworkFlowPayload`, `AuthEventPayload`,
`DnsQueryPayload`, `ProcessExecPayload`, `FileAccessPayload` (sensor payloads,
IP-validated, free-text bounded, case-normalized, cross-field rules) and
`CanonicalEventPayload` + `EntityRef` (normalized view with `raw_event_id`
lineage). Registered in `EVENT_PAYLOAD_REGISTRY` and `SCHEMA_MODELS`;
`gen_contracts.py` emits 34 JSON Schema files. `test_telemetry.py` (13 tests).
Verified: pytest 32 (contracts-py) / 202 (non-integration), mypy --strict clean
(19 files), ruff clean, schema `--check` clean. Commit `ce2d616`.

### Phase 2, Unit 2 — sensor authentication + the ingestion gateway (DONE)

**Step 1 — `SensorAuth`.** `sm_common.security.sensor_auth`: `SensorAuth` /
`SensorIdentity`. Given a presented credential `<sensor_id>.<secret>` (optional
`Bearer ` prefix), it parses, looks up the `sensor` row, verifies the secret
against `credential_hash` with Argon2id (`dummy_verify` for an unknown / malformed
id so there is no timing oracle), then gates on `status == active` and
`deleted_at is null`. Every failure is one generic `Unauthenticated`; the reason
is never returned. `last_seen_at` is touched on success, throttled to one write
per 60s so a chatty sensor does not turn its registry row into a write hot-spot —
so `authenticate` runs inside `Database.transaction()`.

**Step 2 — `services/ingestion-gateway`.** FastAPI service (port 8001,
`python -m sm_ingestion_gateway`):

- `POST /api/v1/ingest/{source_type}` (`network_flow | auth_event | dns_query |
  process_exec | file_access`). Body is the bare payload; the envelope is built
  server-side (`envelope.build_envelope`) — `event_id` UUIDv7, `tenant_id` /
  `source.sensor_id` / `source.type=sensor` **from the `SensorIdentity` only**,
  `occurred_at` lifted from the payload, `producer=ingestion-gateway@0.1.0`,
  `partition_key = <tenant_id>:<primary entity>`. Built as the concrete
  `EventEnvelope[...]` so the sink serializes every payload field.
- `POST /api/v1/ingest/batch` — `{source_type, events:[...]}`, capped at
  `SM_INGEST_BATCH_MAX_EVENTS` (default 500); per-element failures come back in
  `rejected` and are dead-lettered, one bad event does not fail the batch.
- Status codes: `202` accept / `200` duplicate `X-Sensor-Event-Id` / `404`
  unknown `source_type` / `422` (+DLQ) bad JSON or failed schema / `401` any
  sensor-auth failure / `413` over `SM_HTTP_MAX_BODY_BYTES` / `503` limiter-store
  outage.
- `RateLimitMiddleware` gained a `fail_open` flag; the gateway passes
  `fail_open=False` so a Redis outage rejects (`503 dependency_unavailable`)
  instead of letting a flood through. No CORS middleware (sensors aren't
  browsers). No `/docs` in production.
- Idempotency: optional `X-Sensor-Event-Id` in a Redis `SET NX EX` keyed on
  `(sensor_id, id)`, TTL `SM_INGEST_DEDUP_TTL_SECONDS`. A Redis outage returns
  `DedupState.unavailable` and the event is still sinked (downstream is
  idempotent on `event_id`).
- `sinks.py`: `RawEventSink` / `DeadLetterSink` protocols. Unit 2 shipped
  logging stopgaps; Unit 3 (below) added the Kafka implementations behind the
  same interfaces.
- `/healthz`, `/readyz` (postgres + redis [+ kafka when the bus is on]),
  `/api/v1/meta`, `/metrics`
  (`sm_ingest_{accepted,rejected,duplicates,dedup_errors,sink_errors}_total`).

One image (`Dockerfile.app`) now builds both services; the compose `command:`
selects the entrypoint. `ingestion-gateway` is in the default compose profile.

Verified (2026-09-09): pytest **242** non-integration, **59** integration,
`mypy --strict` clean, `ruff` clean, `gen_contracts.py --check` clean.

### Phase 2, Unit 3 — Kafka producer behind `RawEventSink` (DONE)

- `sm_common.bus.EventBusProducer` (aiokafka) — the shared producer wrapper:
  `enable_idempotence=True` (⇒ `acks=all`), bounded `request_timeout_ms`, keyed
  `send_and_wait`, `start()`/`stop()` for the lifespan, `ping()` (forces a
  metadata refresh) for readiness. `from_settings` reads `SM_KAFKA_*`. ADR-004
  updated: **aiokafka** is the chosen client. aiokafka added to `sm-common`
  deps; `[[tool.mypy.overrides]]` for the missing stubs.
- `sm_ingestion_gateway.kafka_sinks`: `KafkaRawEventSink` → `telemetry.raw`
  (canonical JSON, keyed on `partition_key`), `KafkaDeadLetterSink` →
  `telemetry.raw.dlq` (raw body verbatim, `reason` / `source_type` / `sensor_id`
  in headers, keyed on sensor id).
- `build_services` picks the Kafka sinks + opens the producer when
  `SM_EVENT_BUS_ENABLED=true`, else the logging stopgaps. `create_app` refuses
  to start in production with the bus disabled. `/readyz` gains a `kafka` probe
  when the bus is on.
- Pipeline failure policy: a `raw_sink` produce failure → `503`
  `dependency_unavailable` (single and batch — batch aborts, sensor retries the
  whole batch, consumers idempotent on `event_id`), metered
  `sm_ingest_sink_errors_total{sink=raw}`. A `dlq_sink` failure is swallowed and
  metered `{sink=dlq}` so a second sink failure cannot turn a client 4xx into a
  5xx.
- `partition_key` conformed to `event-model.md`:
  `sha256(<tenant_id>:<primary_entity>)[:16]` (was a readable `<tid>:<entity>` —
  an unrecorded Unit 2 divergence, now fixed).
- compose `redpanda` given a dual listener (`INTERNAL://redpanda:9092`,
  `EXTERNAL://localhost:19092`) + healthcheck; CI `integration` job starts
  redpanda as a plain container (service containers can't take a start command).

Verified (2026-09-09): pytest **249** non-integration (7 new — `test_kafka_sinks.py`
4, sink-failure cases in `test_ingest.py` 3), **61** integration (2 new —
`tests/integration/test_ingestion_bus_pg.py`: accepted event round-trips through
`telemetry.raw`; malformed body lands on `telemetry.raw.dlq` with headers —
against real Redpanda + Postgres + Redis). `mypy --strict` clean (90 files),
`ruff` clean, `gen_contracts --check` clean. Compose stack + live end-to-end
verified later the same day — see "Verification performed (Phase 2, Units 2–4)".

### Phase 2, Unit 4 — normalization-engine (DONE)

- `sm_common.bus.EventBusConsumer` (aiokafka): the shared consumer wrapper.
  `enable_auto_commit=False`; `run_once()` handles a poll batch then commits;
  `run()` loops until `stop()`. `from_settings` reads `SM_KAFKA_CONSUMER_GROUP`.
  Plus `dlq_payload(...)` — the canonical DLQ record shape (event-model.md §5):
  original + `{error_type, error_detail, consumer_group, attempts, failed_at}`.
  (Distinct from the ingestion gateway's DLQ, which keeps the raw bytes verbatim
  + headers — a producer-side reject, not a consumer failure.)
- `services/normalization-engine` — a stream processor, HTTP only for health /
  metrics. Lifespan owns the producer, the consumer, and one background task
  running `consumer.run(engine.handle)`.
- `normalize/mappers.py`: one deterministic mapper per `telemetry.*` payload →
  `CanonicalEventPayload` (normalized verb, `actor`/`target` entity refs, full
  entity list incl. DNS answers as ip/domain, flat `attributes`). Lineage
  (`raw_event_id`, `raw_event_type`) and event time come from the source
  envelope. `enrich/` is a stub `Enricher` protocol + runner (empty provider
  list → `enrichment = {}`); a provider that raises is recorded partial, never
  fails the event.
- `engine.py` handler contract with the consumer: a **poison** record
  (unparseable / unknown `event_type` / invalid envelope / mapper bug) → DLQ,
  return (offset commits, partition keeps moving); a **produce** failure →
  retry×3 backoff, then raise (offset not committed, batch redelivered; the
  idempotent producer prevents partition dupes). Metrics
  `sm_normalize_{in,out,dlq,produce_errors}_total`.
- The canonical envelope: new `event_id`, `event_type=event.canonical`,
  `producer=normalization-engine@…`, `tenant_id`/`source`/`correlation_id`/
  `trace_id` copied from the source, `partition_key =
  sha256(<tenant_id>:<actor|target|first entity>)[:16]`,
  `metadata.raw_event_id` set.
- `partition_key` derivation extracted to `sm_contracts.make_partition_key` —
  the ingestion gateway now calls it too (was a private copy).
- `normalization-engine` added to `Dockerfile.app` (one image), compose (`bus`
  profile, `SM_EVENT_BUS_ENABLED=true`), Makefile, CI, isort config.

Verified (2026-09-09): pytest **266** non-integration (17 new —
`test_normalize.py` 6, `test_engine.py` 7, `test_health.py` 4), **63**
integration (2 new — `tests/integration/test_normalization_bus.py`: a
`telemetry.raw` network-flow record becomes an `events.canonical` envelope with
lineage; a poison record lands on `telemetry.raw.dlq` (wrapped) and the next
good record still processes — real Redpanda). §23 review added 3 regression
tests (deterministic canonical `event_id`; corrected-retry dedup; empty DNS
answer). `mypy --strict` clean (106 files),
`ruff` clean, `gen_contracts --check` clean. Compose stack (all 6 containers
healthy) + live end-to-end verified the same day — see "Verification performed
(Phase 2, Units 2–4)". NOT VERIFIED: CI.

### Phase 1 — INTEGRATION VERIFIED on local Docker (kept for the record)

Docker Desktop was installed on the development machine on 2026-09-09 (engine
29.7.2, WSL2 2.5.10). The full compose stack and the integration suite now run
here. The integration verification is done locally:

- `docker compose -f deploy/docker/docker-compose.yml up -d postgres redis` then
  `pytest tests/integration -q -m integration` with `SM_REQUIRE_INTEGRATION=1`:
  **52 passed** against real PostgreSQL 16 and Redis 7.
- Full stack `docker compose up -d --build`: the `migrate` container applied
  `0001 -> 0002` (exit 0); `app` returns `/healthz` 200, `/readyz`
  `{"ready":true}` with live postgres and redis probes, and `/api/v1/meta` 200.
- `docker build -f deploy/docker/Dockerfile.app`: builds; the image runs as uid
  10001; a production CORS wildcard is rejected inside the built image;
  `docker compose config` validates.

Four first-run defects were found and fixed (see the verification section for
Unit 6 — integration). The one remaining gap is the CI workflow: it needs a
GitHub remote and `gh auth login`, then `bash scripts/push_and_watch.sh`. The
local branch was renamed `master -> main` so the `on.push` trigger matches.

Phase 1 is treated as INTEGRATION VERIFIED on local infrastructure; the CI
`integration` and `image` jobs remain the independent confirmation and must run
before Phase 2 is itself declared complete.

## Phase 4 exit report

**State: COMPLETE / CI-VERIFIED (all four jobs, run `34350607501`) against real
Neo4j 5 Community + real Redpanda. GDS pathfinding/centrality and the
operational-graph pruning job are deferred to their consuming phase.**

### Delivered (Units 1–4)

| Area | State |
|---|---|
| `sm_common.graph` | `Graph` async Neo4j driver wrapper (connectivity probe, per-query timeout, `GraphUnavailableError`, parameter-only `run_read` / `run_write`); `apply_pending` migration runner + `split_statements`. |
| `sm_contracts.graph` | the label / relationship **allowlist** (`GRAPH_NODE_KEY` 13 labels, `GRAPH_NODE_LABELS`, `GRAPH_REL_TYPES` 15 types), `normalize_label`, `graph_node_uid`; `GraphEventPayload` + `GraphMutationOutcome` + `EventType.graph_event`. `GraphCommandPayload` promoted **STABLE**. Contract test pins the allowlist to `data-model.md`. |
| `migrations/neo4j/0001_schema.cypher` | per-tenant `uid` UNIQUE constraint per label + `_GraphCommand` / `_GraphMigration` ledgers + tenant-key range indexes + temporal indexes + `Host`/`Domain`/`Identity` full-text. Runner `scripts/graph_migrate.py` (`--status`); `make migrate` applies it; CI `integration` runs it against a real `neo4j:5-community` service. |
| `services/graph-service` | **the only write path into Neo4j.** Consumes `graph.commands` (group `graph-writer`) via `RecordProcessor`; `GraphWriter.apply` — parameterized MERGE (label allowlist-checked, off-list → DLQ), idempotent by `command_id` (`_GraphCommand` ledger), out-of-order safe (`_watermark`), tenant invariants by construction (synthetic `uid`), missing endpoint nodes created thin, no duplicate relationships, `PRUNE` not-yet-implemented → DLQ. `GraphEngine.handle` maps Neo4j outage → `TransientError` and emits `graph.events`. |
| `services/graph-service` query API | `GraphRepository` (`entity` / `neighbors` / `attack_path`) + `GET /api/v1/graph/{entity,neighbors,paths}`. Parameterized only; **tenant scope from the verified internal JWT, never a request field**; depth clamped to `SM_NEO4J_TRAVERSAL_MAX_DEPTH`, row-capped `SM_NEO4J_QUERY_MAX_ROWS`, `_`/`uid` props stripped. `deps.get_principal` is the mesh's first `verify_internal_token` verifier. |
| `AppSettings` | `SM_NEO4J_PASSWORD` production fail-fast guard; `SM_NEO4J_QUERY_MAX_ROWS`, `SM_NEO4J_TRAVERSAL_MAX_DEPTH`. |
| `deploy/docker` | `neo4j` healthcheck (`graph` profile); `graph-service` service (`graph` profile, `depends_on` neo4j healthy, port 8004); one image builds all 6 services. CI: 7th mypy tree, install + import checks, Neo4j service + schema step. |

### End-to-end verification (Unit 4)

`tests/integration/test_graph_pipeline_e2e.py` — real Redpanda + real Neo4j:
a canonical `auth` event on `events.canonical` → `stream-processor` engine →
`graph.commands` → `graph-service` engine → Neo4j. The graph then has
`(:Identity {identity_id:'e2e-alice'})-[:AUTHENTICATED_TO]->(:Host {host_id:'e2e-web01'})`;
`GraphRepository.entity` / `neighbors` / `attack_path` return it; `graph.events`
carries `outcome: APPLIED`. 349 unit tests, ruff, `mypy --strict` over 7 src
trees, 91 integration tests all pass.

### Pre-output engineering review (Constitution §23)

- **Cypher injection.** The only interpolation anywhere is a node label / rel
  type, always after `normalize_label` + a membership check against a frozen
  `frozenset` whose members are compile-time string literals, and it is
  back-tick-quoted. The query-API depth is `max(1, min(int(d), cap))`. Every
  other value is a bound parameter. `test_graph_model.py` fails the build if the
  allowlist drifts from `data-model.md`; `test_repository.py` / `test_writer.py`
  assert the caller's key value never appears in the query text.
- **Tenant isolation.** Node identity is `uid = "<tenant>:<key>"` (UNIQUE), so a
  MERGE_EDGE cannot join two tenants; every read filters
  `all(x IN nodes(p) WHERE x.tenant_id = $tenant)` and the tenant comes from the
  JWT. `test_graph_service_neo4j.py::test_queries_never_cross_tenants` and
  `::test_relationships_never_cross_tenants` prove it against real Neo4j.
- **Idempotency vs. atomicity.** The ledger row is written *after* the
  (idempotent) MERGE, so a crash between them re-runs the MERGE — never a
  command marked done but not applied. Cost: a redelivered STALE/DUPLICATE
  re-runs one idempotent MERGE. Accepted and documented.
- **Auto-commit, single statement.** `graph-writer` applies one command as one
  statement, so auto-commit is correct; a multi-statement transaction would buy
  nothing here. The migration runner is the same.
- **`_watermark` is an internal prop.** Stripped from every query response;
  never part of a key. Node/edge `first_seen` still widens on an out-of-order
  event so temporal-range queries stay correct.
- **Community-edition limits.** No composite `NODE KEY`, no read-only role, one
  database. The synthetic `uid` covers uniqueness; the read/write split is
  enforced in code (writes only via `graph-service`); `graph` property `'op'`/`'kg'`
  is written but the operational/knowledge split by database waits for Enterprise
  (U-003). Documented in ADR-007 and `data-model.md`.

### Deferred (deliberately)

- **GDS** (pathfinding at scale, centrality, community detection) — Phase 5+/
  graph-ML, its consuming phase.
- **Operational-graph pruning job** (retention-window sweep, promote-to-knowledge
  on confirmed chains) — needs the retention config + a scheduler; `PRUNE`
  commands are dead-lettered with a clear message until then.
- **`:Detection` / `:AttackChain` / MITRE nodes** — produced by `detection-engine`
  (Phase 5+); the labels are already on the allowlist.
- **Enterprise features** (multi-database op/kg split, native read-only role,
  clustering) — open licensing question (ADR-007), does not block development.

### Exit criteria status

| Criterion | Status |
|---|---|
| Neo4j integration (driver, config, health) | ✅ `sm_common.graph`, `probe_check("neo4j", …)` |
| Graph repository + node/relationship models | ✅ `GraphWriter` + `GraphRepository`; models = `data-model.md` (locked) |
| Constraints + indexes | ✅ `migrations/neo4j/0001_schema.cypher`, runner, CI applies it |
| Graph update consumer (normalized event → command → mutation) | ✅ `stream-processor` → `graph.commands` → `graph-service` → Neo4j, e2e verified |
| Duplicates / out-of-order / missing nodes / tx failure / Neo4j down / retry | ✅ ledger / `_watermark` / thin-create / `TransientError`; integration tests |
| Never blindly create duplicate relationships | ✅ MERGE on endpoints only; `test_repeated_edge_commands_never_duplicate_the_relationship` |
| All Cypher parameterized; no untrusted interpolation | ✅ allowlist + bound params only; §23 above; contract + unit tests |
| Controlled graph query interfaces | ✅ `GraphRepository` + 3 internal endpoints; no raw-Cypher path |
| Temporal graph representation | ✅ `observed_at` / `first_seen` / `last_seen` on every node+edge; range indexes; `attack_path` |
| Attack-path traversal | ✅ `GraphRepository.attack_path` (`shortestPath`, depth-bounded), real-Neo4j test |
| Tenant isolation | ✅ synthetic `uid` + path filter + JWT tenant; real-Neo4j cross-tenant tests |
| Real Neo4j integration tests | ✅ 20 (`test_graph_schema_neo4j` 6, `test_graph_service_neo4j` 10, `test_graph_pipeline_e2e` 1, + query cases) |
| **CI green on a clean runner** | ✅ **all four jobs — runs `34346140544` / `34348143536` / `34349655012` / `34350607501`** |

## Phase 3 exit report

**State: IMPLEMENTED / INTEGRATION VERIFIED (real Redpanda) for the Kafka
backbone; Units 1–3 CI-green; Unit 4 = this report + decisions. Flink not
implemented (deferred per ADR-010).**

### Delivered (Units 1–4)

| Area | State |
|---|---|
| `sm_contracts.topics` | the definitive 12-topic catalog (`TOPICS`, `TopicSpec`), `EVENT_TYPE_TOPIC` / `topic_for_event_type`, `dlq_topic` / `replay_group`, `EVENT_TYPE_VERSION` + the `.v2` breaking-change policy. STABLE. |
| `sm_contracts.graph` | `GraphCommandPayload` / `GraphOp` / `GraphEndpoint` / `graph_command_id` (CONTRACTS.md §5). STABLE target — consumer is Phase 4. |
| `sm_common.bus` | `EventBusProducer` (idempotent, `acks=all`, `flush` on stop, send-error metric), `EventBusConsumer` (manual commit, **rewind-on-failure**, graceful shutdown, `seek_by_timestamp`, lag/records metrics, backpressure bound), `RecordProcessor` (retry→DLQ), `dlq_payload`, `admin.ensure_topics` (create + grow). |
| `services/normalization-engine` | refactored onto `RecordProcessor`; its bespoke DLQ/retry loop removed; duplicate metrics dropped. |
| `services/stream-processor` | new — `graph-update-emitter` job (`events.canonical` → `graph.commands`), stateless, health/metrics. |
| `scripts/` | `provision_topics.py` (+ `--list`), `replay.py` (dry-run default, `*-replay` group enforced). |
| `deploy/docker` | `topics-init` one-shot, `stream-processor` service (`bus` profile), one image builds all 5 services. |
| `docs/architecture/observability.md` | new — metric catalog + alerts. |
| ADR-010 | revised: engine-independent contracts stand; **plain-Python for stateless jobs**; stateful jobs pick an engine (Bytewax front-runner, Flink if state demands) at their consuming phase. **U-001 / U-002 RESOLVED.** |

### Not implemented (deliberately)

- **Flink / any cluster stream engine** — no JDK 11+ locally (ADR-001); no
  stateful job's consuming phase has arrived. `feature-aggregator`,
  `attack-chain-correlator`, `lateral-movement`, `temporal-stitcher` are
  contracts only (event-model.md §7).
- **Schema registry / Avro** (U-004) — still JSON; the envelope survives the
  switch when volume justifies it.
- **`graph.commands` has no consumer** — `graph-writer` / Neo4j is Phase 4.
- OTLP collector / scraped Prometheus — opt-in, not wired locally.

### Exit criteria status

| Criterion | Status |
|---|---|
| Topic strategy: partitions / keys / retention / ordering / groups / versioned types | ✅ `sm_contracts.topics` + event-model.md §2/§3 |
| Producer / consumer / consumer groups / serialization / schema validation | ✅ `sm_common.bus` + `RecordProcessor` |
| At-least-once / idempotent consumers / duplicates / retries / poison / restart / offsets | ✅ verified (`test_bus_kafka.py`) |
| DLQ topics + handling | ✅ `dlq_payload` → `<topic>.dlq`, consumer + producer sides (event-model.md §5) |
| Replay | ✅ `seek_by_timestamp` + `scripts/replay.py` |
| Graceful shutdown / backpressure / observability | ✅ + `observability.md` |
| Kafka = transport, Flink = stream processing, Redis = cache — no duplication | ✅ ADR-008/009/010; roles documented |
| Flink "only where Phase 0 established it as necessary" | ✅ nowhere yet — deferred, decision recorded |
| Real Kafka integration tests | ✅ 13 against Redpanda (bus 9, norm 2, stream 2) |
| **CI green on a clean runner** | ✅ **all four jobs — run `34342866073`** |

## Phase 4, Unit 1 — Neo4j foundation (DONE — local + unit verified)

- `sm_common.graph.Graph` — one async `neo4j` driver per process. `start()` /
  `ping()` verify connectivity (`ServiceUnavailable` / `OSError` →
  `GraphUnavailableError`, which the caller turns into a 503 / `TransientError`);
  `run_read` / `run_write` take a Cypher string + a parameter dict and run it
  auto-commit with `default_access_mode` READ / WRITE and the configured
  per-query timeout (`SM_NEO4J_QUERY_TIMEOUT_MS`, default 10 s — a slow query
  raises, never hangs). A real `Neo4jError` (constraint violation etc.)
  propagates unwrapped so the writer can decide DLQ vs. retry.
- `sm_contracts.graph` — the Neo4j **label / relationship allowlist**
  (`GRAPH_NODE_KEY` 13 labels + key property, `GRAPH_NODE_LABELS`,
  `GRAPH_REL_TYPES` 15 types), `normalize_label(":Host" → "Host")`,
  `graph_node_uid(tenant_id, key)` → `"<tenant>:<key>"`. Cypher cannot
  parameterize a label or relationship type, so `graph-service` (Unit 2) checks
  every command's label against these sets before building Cypher; anything else
  is dead-lettered. `packages/contracts-py/tests/test_graph_model.py` pins the
  allowlist to `data-model.md` (the only extra beyond the canonical set is
  `ACCESSED`, used by the stream-processor file-access mapper).
- `migrations/neo4j/0001_schema.cypher` + `sm_common.graph.apply_pending`
  (runner) + `scripts/graph_migrate.py` (CLI, `--status`). Versioned `.cypher`
  files applied in filename order, each recorded as a `:_GraphMigration`
  node → re-running is a no-op. 0001 creates: a UNIQUE constraint on the
  synthetic per-tenant `uid` for every node label (Community has no composite
  NODE KEY — data-model.md permits "a synthetic key"), a `_GraphCommand.command_id`
  UNIQUE constraint (idempotency ledger for Unit 2), tenant-scoped
  `(tenant_id, <key>)` range indexes, `last_seen` / relationship `observed_at`
  range indexes, and the `Host.hostname` / `Domain.fqdn` / `Identity.name`
  full-text indexes for hunting.
- `AppSettings` — `SM_NEO4J_PASSWORD` is now a production fail-fast guard (like
  `SM_PG_PASSWORD`); the stale "unused until Phase 2/3" comment is corrected.
- Wiring: `neo4j` gets a compose healthcheck under the `graph` profile;
  `make migrate` now also runs the Neo4j schema; CI `integration` job adds a
  `neo4j:5-community` service + an "Apply Neo4j schema" step; the `image` job's
  entrypoint-import check covers `sm_common.graph` + `neo4j`; the two prod-guard
  image steps carry `SM_NEO4J_PASSWORD`. `.env.example` neo4j block corrected
  (dropped the non-existent `SM_NEO4J_MAX_POOL_SIZE`).
- Tests: `packages/common-py/tests/test_graph_driver.py` (12 — fake driver:
  param / timeout / access-mode pass-through, outage wrapping, `Neo4jError`
  propagation, statement splitter), `test_graph_model.py` (8),
  `test_config.py` (+2). `tests/integration/test_graph_schema_neo4j.py` (6,
  marked `integration`, real Neo4j via the `graph` fixture): migration creates
  constraints + indexes, idempotent re-run, apply-from-bare-schema, `uid`
  uniqueness enforced, parameter values never executed as Cypher, slow query
  hits the timeout. Verified locally against Neo4j 5 Community **and CI-green**
  (run `34346140544`).

## Phase 2 exit report

**State: IMPLEMENTED / INTEGRATION VERIFIED (local + compose + live) / §23
REVIEWED. CI-VERIFIED pending a GitHub remote.**

### Delivered (Units 1–4 + review)

| Area | State |
|---|---|
| `sm_contracts.telemetry` | the 5 sensor payloads + `CanonicalEventPayload` / `EntityRef`; IP-validated, free-text bounded, case-normalized, cross-field rules, lineage. Registered in `EVENT_PAYLOAD_REGISTRY` + `SCHEMA_MODELS`. `make_partition_key` (shared derivation). STABLE target. |
| `sm_common.bus` | `EventBusProducer` (aiokafka, idempotent, `acks=all`), `EventBusConsumer` (manual commit after side effect), `dlq_payload` (event-model.md §5 shape). |
| `sm_common.security.sensor_auth` | `SensorAuth` / `SensorIdentity` — `<sensor_id>.<secret>`, Argon2id, `dummy_verify` for unknown, one generic `Unauthenticated`, throttled `last_seen_at`. |
| `services/ingestion-gateway` | `POST /api/v1/ingest/{source_type}` + `/batch`, per-sensor auth, envelope built server-side (tenant from identity only), fail-closed rate limiter, `X-Sensor-Event-Id` dedup, Kafka `RawEventSink` / `DeadLetterSink` (logging stopgap when the bus is off), health/metrics. |
| `services/normalization-engine` | consumes `telemetry.raw`, deterministic per-source mapping → `CanonicalEventPayload`, produces `events.canonical` with a deterministic `event_id`; poison → `telemetry.raw.dlq`; `enrich/` is a stub protocol (no providers). Pure stream processor + health/metrics. |
| `deploy/docker` | one `Dockerfile.app` builds all four services; compose `ingestion-gateway` (default) + `normalization-engine` (`bus` profile) + `redpanda` (dual listener). **Compose stack run: 6 containers healthy; live end-to-end passed.** |
| `.github/workflows/ci.yml` | `static` / `unit` / `integration` (+ runner-hosted redpanda) / `image` (builds all four services, asserts each imports, + prod-config guards). **CI-VERIFIED** — run `34333269219`, all four jobs green on `ubuntu-latest`. |
| GitHub | `github.com/gaurav685/sentinelmesh` (private). Remote `origin`; branch `main`. |

### Pre-output engineering review (Constitution §23)

Three defects in code that had only run locally, all fixed with a regression
test — see "Pre-output engineering review (Constitution §23) — Phase 2" below:
deterministic canonical `event_id` (idempotency under redelivery); the dedup
mark freed on a 4xx (corrected retry not dropped); empty DNS answer rejected at
the contract boundary. Commit `862eb9e`. Six-role sign-off recorded there.

### First-run CI defect

First push to a clean runner: the `unit` job failed 4 config tests. Root cause —
the workflow set `SM_ENV` / `SM_SERVICE_NAME` / `SM_PG_PASSWORD` /
`SM_INTERNAL_JWT_SIGNING_KEY` / `SM_OIDC_CLIENT_SECRET` as global job env, and
`pydantic-settings` reads OS env regardless of `_env_file=None`, so those leaked
into every `AppSettings` a unit test built (`test_defaults_local` saw `env=ci`;
`test_service_name_required` / `test_production_requires_secrets` stopped
raising; `api-gateway` `test_meta` saw `environment=ci`). Fix: a repo-root
`conftest.py` autouse fixture strips `SM_*` for every non-integration test (unit
tests are hermetic now, regardless of the ambient environment — a developer with
`SM_ENV` exported hit the same latent bug); the `SM_*` block removed from the
workflow's global `env:`. Commit `8064fd9`. Second run: all four jobs green.

### Not verified (the whole list)

- Enrichment: Geo-IP, hostname resolution, identity stitching (`identity_link`),
  threat-intel tagging — protocol only, zero providers. Later units/phases.
- `events.canonical` has no consumer yet (Phase 3 `graph` / `detection`).
- Topic pre-creation with real partition counts (event-model.md) — a deploy-time
  task, auto-created locally / in CI.
- Per-sensor rate quota (currently per-IP).
- Any metric scraped from a real Prometheus; any span at a collector.

### Exit criteria status

| Criterion | Status |
|---|---|
| Every requirement (R1, R2) has a service + code + tests | ✅ |
| Full pipeline works end to end | ✅ live through the compose stack |
| Contracts registered + schema-generated | ✅ |
| `mypy --strict` + `ruff` clean | ✅ (106 files) |
| Unit + integration suites green | ✅ 268 + 63 |
| §23 review done | ✅ 3 defects fixed |
| **CI green on a clean runner** | ✅ **run `34333269219` — all four jobs** |

**Phase 2 is COMPLETE.**

## Phase 1 exit report

### Delivered (Units 1–6 + review)

| Area | State |
|---|---|
| `packages/contracts-py` | envelope, error contract, Phase-1 entities + APIs, enums; JSON-Schema codegen. STABLE. |
| `packages/common-py` | config + production guards, structured logging + redaction, request/correlation IDs, `SmError`, Argon2id, internal JWT, OIDC client, async Postgres + Redis clients, health/metrics/tracing, audit hash chain + `AuditWriter`, FastAPI middleware (context, security headers, body limit, **rate limit**, CORS builder), `client_ip` proxy resolution. |
| `migrations/postgres` | 8 control-plane tables + RBAC seed; `updated_at` and append-only audit triggers; reversible. |
| `services/api-gateway` | local + OIDC login, Redis sessions + CSRF, deny-by-default RBAC, tenant-scoped repositories, audited admin routes, `/healthz` `/readyz` `/health/deps` `/api/v1/meta` `/metrics`, full hardening stack incl. per-caller rate limiting. |
| `deploy/docker` | compose stack + non-root `Dockerfile.app` + Keycloak dev realm + Prometheus config. **Authored, never run.** |
| `.github/workflows/ci.yml` | static / unit / integration (service containers) / image jobs; `SM_REQUIRE_INTEGRATION=1` makes a skipped integration test a failure. **Never run.** |

### Pre-output engineering review (Constitution §23)

Seven defects found in never-run code, all fixed with regression tests:

| # | Defect | Commit |
|---|---|---|
| 1 | Login lockout double-incremented `failed_login_count` (proven red/green) | `5f29957` |
| 2 | An authorization denial became a 500 when the audit write failed | `5f29957` |
| 3 | Client IP taken from a spoofable source (`request.client.host`) | `6e5becc` |
| 4 | 413 body carried a zeroed `request_id` | `6e5becc` |
| 5 | `BodySizeLimitMiddleware` could emit a duplicate `http.response.start` | `6e5becc` |
| 6 | Audit advisory lock on `hashtext` (int4) — widened to int8 | `6e5becc` |
| 7 | Rate limiting specified but never wired | `901d9c1` |

Six-role sign-off (each role reviewed the Phase-1 surface):

- **Principal Engineer** — service boundaries hold; `api-gateway` owns only its
  control-plane tables and the read projections; no service imports another's
  internals; the dependency graph is acyclic. No concern.
- **Security Engineer** — deny-by-default confirmed; identity/tenant/role never
  taken from the request; cross-tenant probes return `not_found`; login has no
  enumeration or timing oracle; parameterized SQL only; CSRF double-submit;
  rate limiting in front of auth. Open items: no account-recovery flow (out of
  Phase-1 scope), and the audit chain's tamper-*detection* has no automated
  *verifier job* yet (recorded as a limitation).
- **SRE** — `readyz` degrades correctly; the limiter and the audit write both
  fail open with a metric; graceful shutdown drains clients. Concern: the
  `require_permission` audit opens a transaction per 403 — acceptable now that
  the limiter caps a probing flood, revisit if authz-denial volume is high.
- **Database Engineer** — every constraint has an integration test (skipped);
  migrations are reversible; the advisory lock serializes audit appends per
  tenant. The `upgrade/downgrade/upgrade` cycle is asserted only in CI, which
  has not run.
- **ML Engineer** — N/A for Phase 1.
- **Frontend Engineer** — the API returns only `sm_contracts` models; the error
  contract, CSRF header and cursor pagination are stable; `contracts-ts` schema
  is generated. No frontend code yet (Phase 4).

### Not verified (the whole list)

- The 49 integration tests: migrations against a real database and the
  reversibility cycle; seed content; `updated_at` and append-only triggers;
  the per-tenant advisory lock under concurrency; every schema constraint; the
  SQL repositories' tenant predicate, soft-delete and pagination; the Redis
  session TTL / absolute deadline; the rate-limit window TTL and rollover.
- The CI workflow: no job has run.
- `docker compose config`, any image build, any container start.
- A real OIDC round-trip against Keycloak.
- Any metric scraped from a running Prometheus; any span at a collector.

**To clear it:** install Docker Desktop and run `make up` then
`make test-integration`, **or** push to GitHub (`bash scripts/push_and_watch.sh`
after `gh auth login`) and let the `integration` and `image` jobs run.

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
| Tests | `python -m pytest packages services tests -q` | **184 passed, 49 skipped** |
| CI config (offline) | `python -m pytest tests/contract/test_ci_config.py -q` | **14 passed** |
| Type check | `python -m mypy --strict --python-version 3.11` over all three packages | **Success: no issues found in 68 source files** |
| Lint | `python -m ruff check packages services tests migrations scripts` | **All checks passed** |
| Skip-guard behaves | same module with and without `SM_REQUIRE_INTEGRATION=1` | **11 skipped** vs **11 errors** — the guard works |

The CI workflow defines four jobs: `static` (ruff + `mypy --strict`), `unit`
(`-m "not integration"` plus `gen_contracts.py --check`), `integration`
(postgres:16 + redis:7 service containers, applies migrations, runs the 49
tests with `SM_REQUIRE_INTEGRATION=1`), and `image` (builds `Dockerfile.app`,
asserts uid 10001, and asserts the production config guard rejects a CORS
wildcard **inside the built image**).

### Pre-output engineering review (Constitution §23) — done while the run is blocked

The review found six defects in Phase-1 code that has never run against real
infrastructure. All fixed, each with a regression test; the login-counter one
was proven red/green.

| # | Defect | Fix | Commit |
|---|---|---|---|
| 1 | Login lockout incremented `failed_login_count` twice — 3 failed attempts left the count at 4 | Split `record_login_failure` (counter) from `set_lockout` (lock) | `5f29957` |
| 2 | An authorization denial became a 500 when the audit write failed, hiding the refusal | Guard the audit write; always return 403; new `sm_audit_write_failures_total` counter | `5f29957` |
| 3 | Client IP taken from `request.client.host` — spoofable / wrong behind a proxy | `resolve_client_ip` honours `X-Forwarded-For` only for `SM_TRUSTED_PROXY_HOPS` (default 0) | `6e5becc` |
| 4 | 413 body carried a zeroed `request_id` | Read the id from the ambient request context | `6e5becc` |
| 5 | `BodySizeLimitMiddleware` could emit a second `http.response.start` (ASGI violation) | Track `response_started`; re-raise instead of double-sending | `6e5becc` |
| 6 | Audit advisory lock keyed on `hashtext` (int4) — 2^-32 tenant collision | `hashtextextended(key, 0)` (int8) — 2^-64 | `6e5becc` |

**Not verified (Phase 1, Unit 6) — superseded 2026-09-09 by the integration run
below.** At the time this was written the workflow had never run and every
integration test was skipped.

## Verification performed (Phase 1, Unit 6 — integration, executed 2026-09-09)

Docker Desktop was installed on the development machine (engine 29.7.2, WSL2
2.5.10). This is the first non-offline verification in the project.

| Check | Command | Result |
|---|---|---|
| Integration suite | `pytest tests/integration -q -m integration` with `SM_REQUIRE_INTEGRATION=1`, against `docker compose up -d postgres redis` | **52 passed** |
| Concurrency (chain fork) | `test_concurrent_appends_do_not_fork_the_chain`, 5 repeated runs | **green every run** |
| Migrations on real Postgres | `migrate` container in `docker compose up -d --build` | `0001 -> 0002` applied, exit 0; `alembic_version = 0002`; 14 permissions, 5 system roles seeded |
| App on the stack | `curl` against the running `app` container | `/healthz` 200, `/readyz` `{"ready":true}` with live postgres+redis probes, `/api/v1/meta` 200 |
| Image build | `docker build -f deploy/docker/Dockerfile.app -t sentinelmesh/app:local .` | builds |
| Image runs non-root | `docker run --entrypoint id sentinelmesh/app:local -u` | `10001` |
| Prod config guard in the image | `docker run -e SM_ENV=production -e SM_CORS_ALLOWED_ORIGINS='*' ... AppSettings()` | rejected: "SM_CORS_ALLOWED_ORIGINS must not contain '*' in production" |
| Compose config | `docker compose --env-file .env -f deploy/docker/docker-compose.yml config` | valid |
| Non-integration suite | `pytest packages services tests -q -m "not integration"` | **189 passed** |
| Type check | `mypy --strict --python-version 3.11` over all three packages | **no issues in 69 source files** |
| Lint | `ruff check packages services tests migrations scripts` | **All checks passed** |
| Contract schema | `python scripts/gen_contracts.py --check` | up to date |

### First-run defects found and fixed

| # | Defect | Fix |
|---|---|---|
| 1 | **Audit hash chain forked under concurrency.** `_last_hash` ordered a tenant's chain by `created_at, id`. `created_at` is captured by the application *before* the serializing advisory lock, and `uuid7` ids are not monotonic within a millisecond, so two concurrent appends for one tenant could read the same predecessor and both chain onto it. `test_concurrent_appends_do_not_fork_the_chain` caught it (9 distinct `prev_hash` for 10 rows). | Added `audit_log.seq` — `BIGINT GENERATED ALWAYS AS IDENTITY`, assigned by the database *inside* the advisory lock — as the canonical chain order (model + migration `0001`, new `uq_audit_log_seq`, new `ix_audit_log_tenant_id_seq`). `_last_hash` now orders by `seq DESC`; `created_at` capture moved inside the lock. |
| 2 | **Migration `0002` downgrade was broken under asyncpg.** `sa.text("DELETE ... WHERE role_id = ANY(:ids::uuid[])")` — SQLAlchemy reads `::` as an escaped colon, so asyncpg received `ANY($1:uuid[])` → `syntax error at or near ":"`. `upgrade -> downgrade -> upgrade` failed. | Rewrote the downgrade with table constructs and typed `.in_()` bindings; hoisted the `permission` / `role` / `role_permission` `sa.table(...)` definitions to module scope so `upgrade` and `downgrade` share them. |
| 3 | **Integration fixtures bound to a dead event loop.** `database` and `cache` were `scope="session"` async fixtures; pytest-asyncio 1.4 gives each test its own loop, so the reused asyncpg/redis clients raised "attached to a different loop" (24 errors). | Made both fixtures function-scoped, matching every other async fixture in the repo. |
| 4 | **`test_head_is_the_expected_revision` asserted against an un-upgraded database.** It ran `alembic current`, which is empty on a fresh database. | Switched to `alembic heads` (reads the migration scripts), and it now also asserts `current` after an `upgrade`. |

### Corrections to earlier counts

The integration suite is **52 tests**, not 49 — the earlier count predates
`tests/integration/test_rate_limit_redis.py` (3 tests). Occurrences of "49
integration tests" elsewhere in this file are historical.

### Still not verified

- The CI workflow: no job has run. It needs a GitHub remote and `gh auth login`,
  then `bash scripts/push_and_watch.sh`. The local branch is now `main` so the
  `on.push` trigger will match.
- A real OIDC round-trip against Keycloak (the `oidc` compose profile was not
  started).
- Any metric scraped from a running Prometheus; any span at a collector.

## Completed files (Phase 2, Units 1–4)

**Created:**

- `packages/contracts-py/src/sm_contracts/telemetry.py` + `tests/test_telemetry.py`
  (Unit 1).
- `packages/common-py/src/sm_common/security/sensor_auth.py`,
  `packages/common-py/tests/test_sensor_auth.py`,
  `tests/integration/test_sensor_auth_pg.py` (Unit 2 step 1).
- `services/ingestion-gateway/` — `pyproject.toml`, `README.md`, and
  `src/sm_ingestion_gateway/`: `__init__.py`, `__main__.py`, `version.py`,
  `app.py`, `deps.py`, `source_types.py`, `envelope.py`, `sinks.py`, `dedup.py`,
  `metrics.py`, `schemas.py`, `pipeline.py`, `routes/{__init__,ingest,health,metrics}.py`;
  `tests/{conftest,test_ingest,test_envelope,test_dedup,test_health}.py`
  (Unit 2 step 2).
- `packages/common-py/src/sm_common/bus/{__init__,producer.py}` (Unit 3 —
  `EventBusProducer`).
- `services/ingestion-gateway/src/sm_ingestion_gateway/kafka_sinks.py`,
  `services/ingestion-gateway/tests/test_kafka_sinks.py`,
  `tests/integration/test_ingestion_bus_pg.py` (Unit 3).
- `packages/common-py/src/sm_common/bus/consumer.py` (`EventBusConsumer`,
  `dlq_payload`) (Unit 4).
- `services/normalization-engine/` — `pyproject.toml`, `README.md`, and
  `src/sm_normalization_engine/`: `__init__.py`, `__main__.py`, `version.py`,
  `app.py`, `deps.py`, `topics.py`, `engine.py`, `metrics.py`,
  `normalize/{__init__,mappers}.py`, `enrich/{__init__,base}.py`,
  `routes/{__init__,health,metrics}.py`;
  `tests/{conftest,test_normalize,test_engine,test_health}.py`;
  `tests/integration/test_normalization_bus.py` (Unit 4).

**Modified:**

- `packages/contracts-py/src/sm_contracts/{__init__,events,jsonschema}.py`,
  `docs/CONTRACTS.md` (Unit 1 — register telemetry payloads, 34 schema files).
- `packages/common-py/src/sm_common/security/__init__.py` (export `SensorAuth`).
- `packages/common-py/src/sm_common/config.py` +`.env.example`
  (`ingest_dedup_ttl_seconds`, `ingest_batch_max_events`).
- `packages/common-py/src/sm_common/fastapi/ratelimit.py` — `fail_open` flag
  (default `True`; ingestion passes `False`), `_send_429` generalized to
  `_send_error`.
- `deploy/docker/Dockerfile.app` (install `ingestion-gateway`, one image for all
  services), `deploy/docker/docker-compose.yml` (`ingestion-gateway` service;
  `redpanda` dual listener + healthcheck), `Makefile`, `pyproject.toml` (isort
  known-first-party; aiokafka mypy override), `.github/workflows/ci.yml`
  (install + `mypy` cover the new service; `integration` job starts redpanda).
- `packages/common-py/pyproject.toml` (aiokafka dep),
  `packages/common-py/src/sm_common/config.py` + `.env.example`
  (`ingest_*`, `kafka_sasl_*`, `kafka_send_timeout_ms`, `event_bus_enabled`;
  `SM_KAFKA_BOOTSTRAP_SERVERS` default → `localhost:19092`).
- `services/ingestion-gateway/src/sm_ingestion_gateway/{app,deps,pipeline,
  metrics,envelope}.py`, `routes/health.py`, `README.md` (Unit 3 — bus wiring,
  sink-failure policy, sha256 `partition_key`).
- `docs/ARCHITECTURE_DECISIONS.md` (ADR-004 client = aiokafka; ADR-008 dual
  listener).
- Unit 4: `packages/contracts-py/src/sm_contracts/{__init__,events}.py`
  (`make_partition_key`), `sm_common/bus/__init__.py`,
  `services/ingestion-gateway/src/sm_ingestion_gateway/envelope.py` (use the
  shared key), `Dockerfile.app` / `docker-compose.yml` (`normalization-engine`),
  `Makefile`, `.github/workflows/ci.yml`, `pyproject.toml`,
  `docs/{CONTRACTS,REQUIREMENTS_TRACEABILITY,architecture/event-model}.md`.

## Verification performed (Phase 2, Units 2–4 — executed 2026-09-09)

| Check | Command | Result |
|---|---|---|
| Non-integration suite | `pytest packages services tests -q -m "not integration"` | **268 passed** (incl. the 3 §23 regression tests) |
| Integration suite | `pytest tests/integration -q` with `SM_REQUIRE_INTEGRATION=1`, real Postgres 16 + Redis 7 + Redpanda v24.2.11 | **63 passed** |
| Ingest → bus | `test_ingestion_bus_pg.py` — POST → `telemetry.raw`; malformed → `telemetry.raw.dlq` | **2 passed** against real Redpanda |
| Bus → canonical | `test_normalization_bus.py` — `telemetry.raw` → `events.canonical` with lineage; poison → `telemetry.raw.dlq` (wrapped), next good still processes | **2 passed** against real Redpanda |
| Type check | `mypy --strict --python-version 3.11` over all five src trees | **no issues in 106 files** |
| Lint | `ruff check packages services tests migrations scripts` | **All checks passed** |
| Contract schema | `python scripts/gen_contracts.py --check` | up to date |
| Compose config | `docker compose --profile bus config` | valid |
| **Compose stack** | `docker compose --profile bus up -d --build` | all 6 containers **healthy** (postgres, redis, redpanda, app, ingestion-gateway, normalization-engine); `migrate` applied `0001 -> 0002` and exited 0 |
| Service readiness (in-container) | `curl :8000/:8001/:8002 /healthz + /readyz` | all `200` / `{"ready":true}`; ingestion-gateway probes `kafka` healthy (`event_bus=True`), normalization-engine probes `kafka_producer` + `kafka_consumer` healthy (`consumer_group=normalization`) |
| **Live end-to-end** | seed a `sensor` row → `POST :8001/api/v1/ingest/network_flow` → consume `events.canonical` | `202` accepted; the canonical event arrived within ~1s: `event.canonical`, `producer=normalization-engine@0.1.0`, `tenant_id` from the sensor (not the body), `payload.kind=network_flow`, `payload.raw_event_id` = the ingest `event_id`, actor/target = src/dst ip |
| Image job (by hand) | the four `image`-job assertions against `sentinelmesh/app:dev` | uid `10001`; all four service packages + `sm_common.bus` + `aiokafka` import; prod CORS wildcard → exit 1; `ingestion-gateway` prod + `SM_EVENT_BUS_ENABLED=false` → `RuntimeError`, exit 1 |

**Not verified:** the CI jobs on a clean runner (no GitHub remote — the
`image`/`integration` steps were run by hand); a real OIDC round-trip; a scraped
Prometheus / collected span.

### Pre-output engineering review (Constitution §23) — Phase 2

Adversarial read of Units 1–4 (code that has only ever run locally). Three
defects, all fixed with a regression test:

| # | Defect | Fix | Commit |
|---|---|---|---|
| 1 | **`normalization-engine` broke `event_id` idempotency.** It stamped a fresh UUIDv7 on the canonical event every time it processed a raw record. Consumption is at-least-once — a rebalance or crash before the offset commits redelivers the batch — so a redelivered raw record produced a *second* canonical event with a *different* `event_id`, which downstream `event_id` dedup (event-model.md §4) cannot suppress → double detection / double graph write. | `canonical_event_id(raw_event_id) = uuid5(fixed-ns, "canonical:"+raw)` — deterministic, so a redelivery produces the identical `event_id`. `test_redelivery_produces_the_same_canonical_event_id`. | �23 |
| 2 | **`ingestion-gateway` dropped a corrected retry.** The dedup key was set (`SET NX`) *before* payload validation. A sensor that sent a malformed body with an `X-Sensor-Event-Id`, got `422`, fixed the body and retried with the same id → the retry was suppressed as a duplicate (`200`) and the corrected event was never sinked. | `Dedup.forget()` deletes the key on every 4xx path; only an *accepted* event keeps its mark. `test_corrected_retry_after_a_422_is_not_suppressed_as_duplicate`. | �23 |
| 3 | **An empty-string DNS answer DLQ'd the whole event.** `DnsQueryPayload.answers` bounded length but not emptiness; `EntityRef(value="")` then failed `min_length` in the mapper, so `normalize_failed` → DLQ instead of a processed event. | `_bounded_answers` rejects an empty answer at the contract boundary (a clear `422` at ingest, not a silent DLQ downstream). Extra assertion in `test_dns_normalizes_type_and_rcode_and_bounds_answers`. | �23 |

Six-role sign-off (Phase-2 surface): **Principal Engineer** — `ingestion-gateway`
and `normalization-engine` own no other service's data; the bus is the only
coupling; `sm_common.bus` is the shared transport, sink/handler semantics are
per-service; dependency graph acyclic. **Security Engineer** — tenant / sensor
identity is server-side only (payloads are `extra="forbid"`, cannot carry
`tenant_id`); one generic `401` for every sensor-auth failure with `dummy_verify`
for unknown ids; ingestion rate limiter fails **closed**; no secret in any error
body or DLQ record. Open: per-sensor rate quota is still per-IP (recorded);
`identity_link` / enrichment providers not built (R2, later). **SRE** — every
produce failure is a `503` + a metric, never a silent drop; the consumer commits
only after the side effect; poison messages never wedge a partition; `/readyz`
degrades on a broker outage. **Database Engineer** — `SensorAuth` touches
`last_seen_at` throttled to 1/min so a chatty sensor is not a write hot-spot;
no new tables this phase. **ML Engineer** — N/A. **Frontend Engineer** — N/A (no
frontend until Phase 4); the canonical schema is generated.

## APIs

Phase-1 request/response models in `sm_contracts.api`; endpoints implemented in
`services/api-gateway`. Base `/api/v1`. Canonical error contract implemented
(`sm_contracts.errors`).

**Phase 2 (`services/ingestion-gateway`, implemented Unit 2):**
`POST /api/v1/ingest/{source_type}` and `POST /api/v1/ingest/batch`, sensor-
authenticated, bodies validated against `sm_contracts.telemetry`, envelope built
server-side. Response models `IngestAccepted` / `BatchIngestResult` are
service-local (`sm_ingestion_gateway.schemas`), not platform contracts.

## Events

Canonical `EventEnvelope[PayloadT]` **implemented + validated** with envelope
rules (UTC normalization, producer format, clock-skew guard). `EventType`
registry present. `EVENT_PAYLOAD_REGISTRY` maps: `UserEventPayload` (Phase 1);
`NetworkFlowPayload`, `AuthEventPayload`, `DnsQueryPayload`, `ProcessExecPayload`,
`FileAccessPayload`, `CanonicalEventPayload` (Phase 2, Unit 1). The five sensor
payloads are **produced onto `telemetry.raw`** by `ingestion-gateway` — Unit 3
wired the real aiokafka producer (idempotent, `acks=all`), verified end-to-end
against Redpanda; malformed bodies go to `telemetry.raw.dlq`.
`normalization-engine` (Unit 4) **consumes `telemetry.raw` and produces
`events.canonical`** — `CanonicalEventPayload` envelopes with `raw_event_id`
lineage — verified end-to-end against Redpanda (`test_normalization_bus.py`).
Poison records → `telemetry.raw.dlq` (wrapped per event-model.md §5). Consumer
commits offsets only after the side effect. The canonical `event_id` is
**deterministic** — `uuid5` of the raw `event_id` — so an at-least-once
redelivery re-emits the identical `event_id` and downstream dedup suppresses it.
`make_partition_key` (shared) is the single `partition_key` derivation. Topic
catalog + semantics in `event-model.md`. At-least-once; exactly-once not claimed.

## Schemas / migrations

- `sm_contracts` JSON Schema: 22 files in `packages/contracts-ts/schemas/`
  (regenerate: `python scripts/gen_contracts.py`; CI: `--check`).
- Postgres: 8 Phase-1 tables **implemented** as SQLAlchemy models
  (`sm_common.db.models`) and as Alembic migrations:
  - `0001_initial` — `tenant`, `permission`, `role`, `user`, `user_role`,
    `role_permission`, `sensor`, `audit_log`; full PK/FK/unique/check/index;
    `sm_set_updated_at()` trigger on `tenant`/`user`/`role`/`sensor`;
    `sm_audit_log_immutable()` BEFORE UPDATE OR DELETE trigger on `audit_log`;
    `audit_log.seq` (`BIGINT GENERATED ALWAYS AS IDENTITY`, `uq_audit_log_seq`) —
    the canonical hash-chain order; `(tenant_id, seq DESC)` plus descending
    `(tenant_id, created_at)` / `(actor_id, created_at)` audit indexes.
    Reversible.
  - `0002_seed_rbac` — 14 permissions, 5 system roles, role→permission grants,
    ids derived via `uuid5` from a fixed namespace (idempotent, exactly
    reversible); downgrade uses typed `.in_()` bindings (not `ANY(::uuid[])`).
  - Enum columns are `varchar` + `CHECK` rendered from the `sm_contracts`
    enums; a drift-guard test asserts every enum value appears in its CHECK.
  - `identity_link` remains **Phase 2** (owned by `normalization-engine`).
  - **Applied to a real PostgreSQL 16 on 2026-09-09** — `upgrade head`,
    `upgrade -> downgrade -> upgrade`, seed idempotency and the triggers are all
    covered by the passing integration suite.
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
| Docker Desktop | local `docker-compose` (Postgres, Redis, Keycloak, Redpanda, Neo4j, MinIO, Prometheus, Grafana, MLflow) | **INSTALLED 2026-09-09** (engine 29.7.2, WSL2 2.5.10); postgres/redis/migrate/app stack and the 52 integration tests run locally |
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

**Phase 4 is COMPLETE and CI-VERIFIED** (Units 1–4; final run `34350607501`).

**Phase 5 Unit 1 (contracts + `0003` migration) is code-complete and locally
verified** (359 unit tests, ruff, `mypy --strict`, `gen_contracts --check`; 6
real-PG detection-model tests + the migration up/down/up cycle). **Commit Unit 1,
push, confirm CI green.**

**Then Phase 5, Unit 2 — `packages/ml-py` (`sm_ml`).** The feature + model layer:
versioned `FeatureSchema` + `FEATURE_SCHEMA_VERSION` + per-`CanonicalKind`
deterministic extractors (numpy-free); `Preprocessor` (fit/transform, versioned);
the `AnomalyModel` protocol + a numpy/statistics `StatisticalModel` (MAD z-score /
rolling quantile — always available, the ADR-013 degraded path), an
`IsolationForestModel` (sklearn, `sm-ml[serving]` extra), an `AutoencoderModel`
architecture spec + `NOT_TRAINED` guard; a `ModelRegistry` loading artifacts from
`SM_ML_MODEL_DIR`; `ml/models/<name>/CONTRACT.md` per CONTRACTS.md §6 with
`METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`.
Unit 3 = `services/ml-inference` (ADR-013 in-process serving, typed
`MODEL_UNAVAILABLE`). Unit 4 = `services/detection-engine` (rules + composite
deterministic score + adaptive thresholds + evidence + alert + `detections`
topic + degrade-on-model-failure). Unit 5 = wiring + e2e + exit report + §23 +
`REQUIREMENTS_TRACEABILITY` R5/R8/R20.

Exit next action after Phase 5: **PHASE 6 — THREAT INTELLIGENCE + MITRE ATT&CK**
(user pastes the prompt; do not start speculatively).

### Standing debt carried past Phase 2

- Topics are now provisioned by `ensure_topics` — the compose `topics-init`
  one-shot and the CI `integration` job's "Provision Kafka topics" step both
  run `scripts/provision_topics.py` before any consumer/producer starts (and an
  under-provisioned auto-created topic is grown). A real deployment still runs
  its own IaC.
- The `ingestion-gateway` per-IP rate limiter is a placeholder; per-sensor
  quota (keyed on the resolved `SensorIdentity`, after auth) is the intended
  design and is deferred to a later unit.
- `last_seen_at` is touched on every authenticated ingest (throttled to 1/min
  per sensor). Revisit if sensor counts get large — a batched async update
  would remove the write from the hot path.

### Superseded plan for Phase 1 Unit 6 (kept for the record)

**PHASE 1, Unit 6 (remaining) — close out Phase 1.** Blocked until Docker is
available, by either route (`make up` + `make test-integration`, or push to
GitHub). Then: record the real output, fix first-run failures, add the
end-to-end OIDC sign-in, and promote traceability statuses to
`INTEGRATION VERIFIED` only for what the run proves.

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
| 2026-09-09 | 1 (Unit 6 — integration) | Docker Desktop installed on the dev machine (engine 29.7.2, WSL2 2.5.10). First non-offline verification: **52 integration tests pass** against real PostgreSQL 16 + Redis 7; full `docker compose` stack (postgres/redis/migrate/app) comes up, migrations apply `0001 -> 0002`, `/healthz` + `/readyz` + `/api/v1/meta` green; image builds, runs as uid 10001, rejects a prod CORS wildcard. Four first-run defects fixed: (1) audit hash chain forked under concurrency — added DB-assigned `audit_log.seq` identity column as the canonical chain order, `_last_hash` orders by it; (2) migration `0002` downgrade broken under asyncpg (`ANY(:ids::uuid[])`) — rewritten with typed `.in_()`; (3) session-scoped integration fixtures clashed with pytest-asyncio per-test loops — made function-scoped; (4) `test_head_is_the_expected_revision` asserted against an un-upgraded DB — uses `alembic heads`. Non-integration suite 189 passed, mypy --strict clean (69 files), ruff clean. Branch renamed `master -> main`. Remaining: the CI `integration`/`image` jobs (need remote + `gh auth login`). |
| 2026-09-08 | 0 | Repo created at `C:\Users\gmalh\sentinelmesh`; skeleton + doc set; ADR-001…024; all 38 requirements traced. Commit `0b91ed2`. Status: NOT LOCKED. |
| 2026-09-08 | 0 (close) | `packages/contracts-py` implemented (envelope, error contract, Phase-1 entities + APIs, enums); `scripts/gen_contracts.py` + `packages/contracts-ts` schemas; consistency-review pass (2 fixes). Verified: pytest 19 passed, mypy --strict clean, ruff clean, codegen + `--check` pass. **Architecture status: LOCKED.** |
| 2026-09-08 | 1 (Unit 1) | `packages/common-py` platform primitives: `config` (typed `AppSettings`, startup validation, production guards), `logging` (structlog JSON + redaction), `redaction`, `context`, `ids` (uuid7), `clock`, `errors` (`SmError` → canonical `ErrorResponse`), `security.passwords` (Argon2id + dummy-verify), `security.jwt_internal` (mint/verify + rotation), `observability.health`, `fastapi` (request-context middleware, exception handlers, security headers, body-size limit, CORS builder). Verified: **pytest 64 passed** (19+45), mypy --strict clean (17 files), ruff clean. Root pytest `--import-mode=importlib`; ruff `line-length=120`, `**/errors.py` N818 ignore. |
| 2026-09-08 | 1 (Unit 2) | `packages/common-py` infra clients: `db` (async SQLAlchemy 2 engine, `Database` session/`transaction()`/`ping`), `cache.redis` (`Cache` + key prefix + `ping`), `security.oidc` (`OidcClient` — discovery cache, PKCE `S256`, auth URL, code exchange, ID-token verify via `PyJWKClient`+`anyio.to_thread`), `observability.metrics` (`Metrics` + per-process registry), `observability.tracing` (OTLP bootstrap, no-op without endpoint), `audit.hashing` (per-tenant hash chain primitives). Verified: **pytest 81 passed** (19+62), mypy --strict clean (27 files), ruff clean. Deps added: sqlalchemy[asyncio], asyncpg, redis, prometheus-client, opentelemetry-sdk + otlp-http, httpx, anyio; dev respx. |
| 2026-09-09 | 1 (Unit 6 + review) | Fixed-window `RateLimitMiddleware` on the api-gateway (keyed on the resolved client IP, fails open with `sm_rate_limiter_errors_total`, health/metrics exempt, 429 in the canonical shape). Pre-output §23 review: 7 defects found and fixed in never-run code (login-lockout double count — red/green; 403->500 on audit failure; spoofable client IP; zeroed 413 request_id; possible duplicate response-start; int4 audit lock; rate limiting unwired). Six-role sign-off recorded. CI workflow schema hardened; `scripts/push_and_watch.sh` added. Verified: **pytest 189 passed / 49 skipped**, mypy --strict clean (69 files), ruff clean. **Phase 1 exits IMPLEMENTED / LOCALLY VERIFIED; INTEGRATION NOT VERIFIED — 49 tests, image build and CI all still blocked on Docker/remote.** Commits `5f29957`, `6e5becc`, `806285c`, `9843924`, `901d9c1`, `cbe3462`. |
| 2026-09-09 | 1 (review) | Pre-output engineering review (§23) of Phase-1 code while the integration run stays blocked: 6 defects found and fixed with regression tests — login-lockout double count (proven red/green), a 403 masked as 500 on audit failure, a spoofable client IP, a zeroed request_id in the 413 body, a possible duplicate `http.response.start`, and an int4 audit advisory lock. Verified: **pytest 184 passed / 49 skipped**, mypy --strict clean (68 files), ruff clean. Commits `5f29957`, `6e5becc`. |
| 2026-09-08 | 1 (Unit 6, partial) | `.github/workflows/ci.yml` (static / unit / integration with postgres+redis service containers / image build with non-root and production-config-guard assertions); `SM_REQUIRE_INTEGRATION=1` makes an unreachable dependency a failure rather than a skip, so CI cannot go green on a missing database; 14 offline CI-config checks; `README.md` rewritten with real status and setup. Verified: **pytest 172 passed / 49 skipped**, ruff clean, and the skip-guard exercised directly (11 skipped vs 11 errors). **Workflow never run; no image built; 49 integration tests still unexecuted.** |
| 2026-09-08 | 1 (Unit 5) | `deploy/docker` compose stack (core: postgres/redis/migrate/app; profiles: oidc/obs/graph/bus/objects), multi-stage non-root `Dockerfile.app`, Keycloak dev realm (confidential client, PKCE S256, password grant off), Prometheus config, `.dockerignore`, `Makefile`, `/metrics` route, 49 integration tests and 15 offline deployment-config checks. Verified: **pytest 158 passed / 49 skipped**, mypy --strict clean (67 files), ruff clean. **Docker not installed — no image built, no container started, zero integration tests executed.** |
| 2026-09-08 | 1 (Unit 4) | `services/api-gateway`: app factory + hardening stack, `/healthz` `/readyz` `/health/deps` `/api/v1/meta`, Redis-backed sessions + CSRF double-submit, `get_principal` (privileges re-resolved per request), deny-by-default `require_permission` with metered + audited denials, tenant-scoped repositories, Argon2id local login with lockout and no enumeration/timing oracle, OIDC authorization-code + PKCE + state + nonce with no auto-provisioning, `/me`, audited admin user/role routes, explicit ORM→contract mappers. Verified: **pytest 143 passed**, mypy --strict clean (66 files), ruff clean. **No real Postgres/Redis/OIDC yet.** |
| 2026-09-08 | 1 (Unit 3) | `sm_common.db.base`/`models` (8 Phase-1 tables, UUIDv7 PKs, enum CHECKs rendered from `sm_contracts`, role partial unique indexes, security state kept out of contracts); `sm_common.audit.writer.AuditWriter` (per-tenant advisory lock, hash chain, runs in caller's transaction); `migrations/postgres` (alembic.ini + async env.py + `0001_initial` with `updated_at` and append-only audit triggers + `0002_seed_rbac` with 14 permissions / 5 system roles / grants, uuid5-derived ids). Verified: **pytest 102 passed**, mypy --strict clean (30 files), ruff clean, `alembic upgrade head --sql` emits full DDL offline. **Migrations never applied to a real database** (no Docker). Dep added: alembic 1.19.2. |
