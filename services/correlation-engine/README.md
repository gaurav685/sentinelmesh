# correlation-engine

Turns the `detections` stream into multi-stage **attack chains** and a
deterministic chain threat score (req 6, req 8). Port 8009. Health / metrics +
the internal chain read API; no HTTP ingest.

## What it does

Consumes `detections` (group `correlation`). For each `DetectionPayload`:

1. **Resolve the subject** — the detection's `subject_type` / `subject_id`, else
   its first entity, else a host placeholder.
2. **Stage it** — the furthest non-`unknown` kill-chain stage the detection's
   ATT&CK techniques imply (`sm_contracts.stage_for_technique`). A technique with
   no known mapping lands on `AttackStage.unknown` — never a guess. A
   `rule.ti.*` detection marks the chain threat-intel-corroborated.
3. **Correlate** — one chain per `(tenant, subject)` inside a fixed **tumbling
   window** (`SM_CHAIN_WINDOW_SECONDS`, default 24h). The chain id is
   deterministic, so an at-least-once redelivery upserts. Each stage keeps the
   set of detection ids behind it (duplicates are no-ops) and `min`/`max`
   timestamps (out-of-order events reshape it correctly).
4. **Recompute** — `progression` (furthest kill-chain position / 14),
   `confidence` (probabilistic, capped at 0.95 — **never a certainty**; grows
   with distinct ordered stages, discounted when stages ran backwards in time),
   `status` (forming / active / dormant — never auto-`confirmed`), and a
   **versioned deterministic** `score` (`CHAIN_SCORE_VERSION`) over severity,
   anomaly, threat-intel, progression and confidence. Asset-criticality and
   identity-risk are accepted as scorer inputs and renormalise the weighting when
   supplied — no registry feeds them yet.
5. **Emit** `AttackChainPayload` on `attack_chains`.

Poison record → `detections.dlq`; a DB write or a failed produce → retried.

## API

Internal, service-JWT (audience `correlation-engine`), tenant from the token:

- `GET /api/v1/chains?status=&min_score=&limit=` — chain summaries (no per-stage
  detail).
- `GET /api/v1/chains/{chain_id}` — the full chain with its stages.

## Non-fabrication

No validated scoring performance is claimed. `confidence` and `progression` are
explicitly probabilistic and bounded below certainty. Stage assignment is a
lookup, and `TECHNIQUE_STAGE` covers only the techniques SentinelMesh's own rules
emit — it is not a claim of ATT&CK coverage.

## Run

```bash
python -m sm_correlation_engine
```
