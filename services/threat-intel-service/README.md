# threat-intel-service

IOC store of record + enrichment (req 9, TB-4). Port 8007. Health / metrics +
the internal API; no HTTP ingest of telemetry.

## Never fabricates

An indicator only exists because something put it here, and every one carries a
`Provenance` (`provider`, `source_kind`, `reference`, `retrieved_at`). A value
that fails `normalize_indicator_value` is **rejected** (422 on submit; dropped
from a provider feed). Deterministic local test data is labelled
`source_kind = FIXTURE` and `provenance.provider = "fixture:<name>"`.

## Store

`threat_indicator` — dedup on `indicator_dedup_key`: global (`tenant_id IS NULL`)
vs tenant-submitted `(tenant_id, type, value)`. A repeat upsert widens
`first_seen` / `last_seen` and refreshes confidence / reputation / expiry; it
does not add a row. **Reputation** is rule-based (confidence + tags), deterministic.

**Freshness** is derived on read (`freshness_for` against
`SM_TI_DEFAULT_TTL_SECONDS`): `fresh` (≤ TTL) → `aging` (≤ 2×) → `stale` →
`expired` (past `expires_at`).

## API (internal, service-JWT, audience `threat-intel-service`)

- `POST /api/v1/ti/enrich` — `{items: [{type, value}]}` → an `EnrichmentMatch`
  per input (matched only if the row exists and is not expired).
- `GET  /api/v1/ti/indicators` — global + this tenant's, newest first.
- `POST /api/v1/ti/indicators` — submit a tenant-scoped indicator
  (`source_kind = manual`). Emits `ti.updates`.

## ti.updates + expiry

Produces `TiUpdatePayload` on `ti.updates` for every add / update. A background
sweep (`SM_TI_EXPIRY_SWEEP_SECONDS`) finds indicators whose `expires_at` crossed
into the past since the previous run and emits one `expired` update each (cold
start looks back one interval only).

## Providers

External TI provider adapters are Phase 6 Unit 4 (`sm_ti_service.providers`).
`SM_TI_PROVIDERS` (comma-separated) is empty by default — no outbound calls.

## Run

```bash
python -m sm_ti_service
```
