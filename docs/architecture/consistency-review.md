# Phase 0 consistency-review pass

Purpose: a second read of the Phase-0 doc set + `CLAUDE.md` for internal
contradictions before declaring the architecture LOCKED (Engineering Constitution
§23, and the Phase-0 lock criterion "no unresolved critical architectural
contradiction").

Date: 2026-09-08. Reviewer pass: single, structured (author self-review — no
second engineer available in this environment; recorded as such).

## Method

Checked pairwise for conflict:

- service count and names across `overview.md`, `service-catalog.md`,
  `repository.md`, `IMPLEMENTATION_STATE.md`, the actual `services/` directory
- single-writer / data-ownership claims across `data-model.md`,
  `service-catalog.md`, `CONTRACTS.md §4`, `REQUIREMENTS_TRACEABILITY.md`
- Kafka / Redis / Flink role separation (ADR-008/009/010 vs `event-model.md` vs
  `service-catalog.md`)
- Phase assignment of each table/topic/endpoint (data-model vs traceability vs
  implementation-state)
- `CLAUDE.md` rules vs the ADRs and contracts
- non-fabrication: every performance/latency/accuracy/deployment field

## Findings

### F-1 — Service count inconsistent (FIXED)

`IMPLEMENTATION_STATE.md` and `ARCHITECTURE_DECISIONS.md` referred to "21" / "~20"
logical services. The actual set is **18 services** (`services/` directory) plus
**3 shared packages** (`contracts-py`, `contracts-ts`, `common-py`) plus the
frontend. `federation-service` is included in the 18 (deferred implementation,
ADR-023, but it is a real ownership boundary).

Fix: `IMPLEMENTATION_STATE.md` and ADR-002 corrected to "18 logical services + 3
shared packages + frontend". The Phase-0 docs commit message (`0b91ed2`) still
says "21 logical services" and cannot be edited; this note is the correction of
record.

### F-2 — `identity_link` ownership conflict (FIXED)

`data-model.md` and `CONTRACTS.md §4` correctly assign `identity_link` to
`normalization-engine` (Phase 2). `service-catalog.md` (api-gateway entry) and
`IMPLEMENTATION_STATE.md` (Phase-1 migration list) incorrectly listed it as an
api-gateway / Phase-1 table.

Fix: removed `identity_link` from the api-gateway owned-data list and from the
Phase-1 migration set. Phase-1 Postgres tables are exactly:
`tenant`, `user`, `role`, `permission`, `user_role`, `role_permission`,
`sensor`, `audit_log`.

### F-3 — `CLAUDE.md` vs ADRs — no contradiction

`CLAUDE.md` §9 ("Never claim exactly-once … unless actually configured and
verified") matches ADR-008 / `event-model.md §4` (at-least-once, exactly-once not
claimed). §13 (ML: implement pipeline, never claim performance) matches
ADR-012/024. §5 (Argon2id) matches ADR-016 / `security-model.md §2`. §6 (tenant
isolation server-side) matches ADR-017. §19 (complete files, no `...`/`pass`/
`TODO`) is consistent with the contracts-py implementation (no stubs). No
conflict found.

### F-4 — Kafka / Redis / Flink separation — consistent

ADR-008 (Kafka = durable bus), ADR-009 (Redis = cache/session/rate-limit/
fan-out, **not** the bus; Redis Streams only for WebSocket fan-out), ADR-010
(Flink = stateful processing, reads/writes Kafka, does not write Neo4j/Postgres
directly) agree with `event-model.md` and every `service-catalog.md` entry
(`stream-processor` "DB: none"; `graph-service` sole Neo4j writer;
`detection-engine` sole writer of `detection`/`anomaly`/`threat_score`).

### F-5 — Phase numbering — consistent

`REQUIREMENTS_TRACEABILITY.md` phase map (P1..P10, P38), the per-requirement
`Phase` field, and `IMPLEMENTATION_STATE.md` "Exact next action" all agree:
Phase 1 = Foundation/Config/DB/Auth; Phase 2 = Telemetry+Normalization; etc.
`data-model.md` Phase-1 subset (★) matches the Phase-1 migration list after F-2.

### F-6 — Non-fabrication — clean

`grep` for benchmark/latency/accuracy/deployment claim language over `docs/`,
`README.md`, `CLAUDE.md` returns only negations and prohibitions. Every ML
metric field reads `NOT VERIFIED — REQUIRES REAL DATA / TRAINING ENVIRONMENT`;
every deployment/infra field requiring Docker/K8s/Flink/GPU/cloud reads
`NOT VERIFIED — REQUIRES EXTERNAL INFRASTRUCTURE`. `IMPLEMENTATION_STATE.md`
"Verification performed" lists only commands actually run with their actual
output.

## Outcome

Two inconsistencies (F-1, F-2) found and fixed. No critical architectural
contradiction. Lock criterion satisfied.
