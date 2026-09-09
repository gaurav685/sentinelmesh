# graph-service

The only write path into Neo4j (ADR-007, `docs/architecture/data-model.md`).

## What it does

Consumes `graph.commands` (consumer group `graph-writer`) and applies each
`GraphCommandPayload` to Neo4j:

- **Parameterized Cypher only.** The single thing ever interpolated into a query
  is a node label or relationship type, and only after it passes the
  `sm_contracts` allowlist (`GRAPH_NODE_LABELS` / `GRAPH_REL_TYPES`) — Cypher
  cannot parameterize those. A label that is not on the list → `graph.commands.dlq`.
- **Idempotent by `command_id`.** A redelivered command is a `DUPLICATE` no-op
  (`_GraphCommand` ledger, backed by a UNIQUE constraint).
- **Out-of-order safe.** Every node and relationship carries a `_watermark` (the
  newest `observed_at` applied). An older command adjusts `first_seen` /
  `last_seen` bounds but never rolls back properties (`STALE`).
- **Tenant invariants.** `tenant_id` is written onto every node and relationship;
  node keys are the synthetic per-tenant `uid`, so a relationship can only ever
  join two nodes of the same tenant.
- **Missing endpoint nodes** for an edge are created thin, not failed.
- **Neo4j down** → `TransientError` → the record is retried, not dropped.

Emits `graph.events` (outcome + counts) for the read-model projection and
notification fan-out.

No HTTP ingest. The only routes are `/healthz`, `/readyz`, `/api/v1/meta`,
`/metrics`. Port 8004. The read-query API is Phase 4 Unit 3.

## Run

```bash
python -m sm_graph_service
```

Config: `SM_KAFKA_*`, `SM_NEO4J_*` (see `.env.example`). Apply the Neo4j schema
first: `python scripts/graph_migrate.py`.
