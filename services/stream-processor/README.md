# stream-processor

Stream jobs over `events.canonical`. A stream processor with a health / metrics
HTTP surface only; the work is in the Kafka consume loop.

## Jobs

| Job | In | Out | State | Status |
|---|---|---|---|---|
| `graph-update-emitter` | `events.canonical` | `graph.commands` | none | **implemented** (Phase 3) |
| `feature-aggregator` | `events.canonical` | `features.derived` | keyed windows | not implemented — needs a stateful engine (ADR-010) |
| `attack-chain-correlator` | `events.canonical`, `detections` | `attack_chains` | keyed session state | not implemented |
| `lateral-movement` | `events.canonical` | `graph.commands`, `detections` | keyed state | not implemented |
| `temporal-stitcher` | `events.canonical` | `identity.links` | keyed state | not implemented |

`graph-update-emitter` is stateless — a pure map from one canonical event to a
set of `GraphCommandPayload` (`MERGE_NODE` for each entity, `MERGE_EDGE`
`actor -[REL]-> target`, `REL` from the canonical `kind`). Every command id is
`uuid5` of the source canonical `event_id`, so an at-least-once redelivery
re-emits identical ids and `graph-writer` (Phase 4) dedups.

The stateful jobs are **not** built here. No JDK 11+ is available for Flink
(ADR-001) and no consuming phase for those outputs has arrived. The
engine-independent stream contracts are in `docs/architecture/event-model.md §7`;
the engine decision is ADR-010 (U-001 / U-002).

## Delivery

`sm_common.bus.EventBusConsumer` (manual commit after the side effect, rewind on
handler failure) + `RecordProcessor` (retry then DLQ, event-model.md §4/§5).
Poison canonical records → `events.canonical.dlq`.

## Run locally

```
pip install -e "packages/contracts-py[dev]" -e "packages/common-py[dev]" -e "services/stream-processor[dev]"
python -m sm_stream_processor   # port 8003; needs Kafka + a group in SM_KAFKA_CONSUMER_GROUP
```

## Test

```
pytest services/stream-processor            # emitter + engine + health, no broker
```

`tests/integration/test_stream_processor_bus.py` runs the full loop against real
Redpanda.
