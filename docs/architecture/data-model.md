# Data model

State-ownership rule (ADR-011, Constitution §10): no entity is written by more
than one service; no state is duplicated across stores without the reason stated
here.

## Store responsibilities

| Store | Holds | Not for |
|---|---|---|
| **PostgreSQL** | System of record for control-plane + analytical entities: tenants, users, RBAC, assets, identities, sensors, detections, anomalies, scores, alerts, investigations, incidents, MITRE catalog + mappings, threat indicators/actors, analyst artifacts, agent tasks, response actions + policy, threat memory (+ vectors), campaigns, simulations, reports, benchmark experiments, audit log, read models/projections. | high-volume raw telemetry (that is the Kafka log), graph traversal |
| **Neo4j** | Operational attack graph (hot window) + persistent knowledge graph (curated). Entities and their relationships for traversal/visualization/graph-ML. | authoritative business records (those live in Postgres), time-series |
| **Redis** | Caches, sessions, rate-limit counters, consumer dedup sets, advisory locks, WebSocket fan-out streams. All ephemeral/rebuildable. | anything that must survive a restart or be read back by analytics |
| **Kafka** | The durable, replayable event log (raw + canonical + derived). | point lookups, mutable state |
| **S3 / MinIO** | Model artifacts, Flink checkpoints, generated report PDFs, simulation bundles, feature caches. | structured queryable data |

**Deliberate duplication (documented):**

- *Detections* exist in Postgres (`detection`, owned by `detection-engine`) **and**
  as a projection `detection_read` (owned by `api-gateway`, built from Kafka
  `detections`). Reason: read/write separation — the SOC UI needs denormalized,
  filtered, paginated reads without loading the detection service; the projection
  is derived and disposable (rebuildable by replay).
- *Entities* (IP, user, host, domain, process) appear as Neo4j nodes **and** as
  Postgres `asset`/`identity` rows. Reason: Neo4j node = relationship/traversal
  view; Postgres row = lifecycle, ownership, tenancy, criticality metadata.
  `asset_id` is the shared key; Postgres is authoritative for attributes, Neo4j
  for relationships.

---

## PostgreSQL — entities (Phase 1 subset marked ★)

All tenant-scoped tables have `tenant_id UUID NOT NULL REFERENCES tenant(id)`,
`created_at timestamptz NOT NULL DEFAULT now()`, `updated_at timestamptz NOT NULL
DEFAULT now()` (trigger-maintained). Soft-delete via `deleted_at timestamptz`
only where lifecycle requires it (users, sensors, policies). UUIDv7 primary keys.

### Control plane (Phase 1) ★

| Table | Key columns | Constraints / indexes | Notes |
|---|---|---|---|
| `tenant` ★ | `id`, `slug` UNIQUE, `name`, `status` (`active`/`suspended`), `settings jsonb` | `slug` unique, check `status in (...)` | root of all scoping; **not** tenant-scoped itself |
| `user` ★ | `id`, `tenant_id`, `external_subject` (OIDC `sub`), `email` CITEXT, `display_name`, `status`, `password_hash` (nullable — federated users have none), `failed_login_count`, `locked_until`, `last_login_at`, `deleted_at` | UNIQUE `(tenant_id, email)`, UNIQUE `(tenant_id, external_subject)`, index `(tenant_id, status)`, check `status in ('active','disabled','invited')` | `password_hash` Argon2id; local auth is fallback, OIDC primary |
| `role` ★ | `id`, `tenant_id` (nullable → system role), `name`, `description`, `is_system bool` | UNIQUE `(coalesce(tenant_id,'00000000-...'), name)`, check | system roles: `platform_operator`, `tenant_admin`, `lead`, `analyst`, `read_only` |
| `permission` ★ | `id`, `code` UNIQUE (`e.g. detections:read`), `description`, `resource_type`, `action` | UNIQUE `code` | seeded, immutable set; deny-by-default means absence = no access |
| `user_role` ★ | `user_id`, `role_id`, `granted_by`, `granted_at` | PK `(user_id, role_id)`, FK cascade on user delete | |
| `role_permission` ★ | `role_id`, `permission_id` | PK `(role_id, permission_id)` | |
| `sensor` ★ | `id`, `tenant_id`, `name`, `credential_hash`, `type`, `status`, `last_seen_at`, `deleted_at` | UNIQUE `(tenant_id, name)`, index `credential_hash` | sensor's `tenant_id` is authoritative for its telemetry |
| `audit_log` ★ | `id`, `tenant_id` (nullable for platform events), `actor_type`, `actor_id`, `action`, `resource_type`, `resource_id`, `result` (`allow`/`deny`/`success`/`failure`), `request_id`, `correlation_id`, `ip`, `metadata jsonb`, `prev_hash`, `hash` | index `(tenant_id, created_at desc)`, index `(actor_id, created_at desc)` | append-only (no update/delete grant); `hash = H(prev_hash ‖ row)` per tenant chain |
| `identity_link` | `id`, `tenant_id`, `primary_identity`, `linked_identity`, `link_type`, `confidence`, `first_seen`, `last_seen` | UNIQUE `(tenant_id, primary_identity, linked_identity)` | owned by `normalization-engine` |

### Core runtime (Phase ≥ 2, listed for completeness)

`asset`, `identity`, `ip_address`, `domain`, `process_signature`,
`network_flow_summary` (partitioned by day), `dns_query_summary`,
`auth_event_summary`, `endpoint_event_summary`, `anomaly`, `detection`,
`threat_score`, `security_alert`, `investigation`, `incident`.

### Advanced / enterprise (Phase ≥ 3)

`attack_tactic`, `attack_technique`, `attack_matrix_version`,
`technique_mapping`, `attack_chain`, `attack_chain_stage`,
`threat_indicator`, `threat_actor`, `ti_source`,
`analyst_message`, `explanation`, `narrative`, `root_cause_analysis`,
`hunt_query`, `agent_task`, `response_action`, `response_policy`, `approval`,
`threat_memory` (+ `embedding vector`), `campaign`, `campaign_similarity`,
`adversary_fingerprint`, `simulation`, `simulation_run`, `scenario`,
`digital_twin_model`, `decoy`, `decoy_interaction`, `adversary_profile`,
`report`, `report_template`, `benchmark_experiment`,
`detection_read` (projection), `alert_read` (projection).

Each gets its own migration with full PK/FK/unique/check/index definitions when
its phase lands. **No table is created before its phase.**

### Migration discipline

- Alembic, one linear history, `migrations/postgres/versions/`.
- Every migration reversible (`downgrade` implemented) unless irreversible by
  nature (documented in the migration docstring).
- Additive-first: new columns nullable or defaulted; drops happen a phase later
  after code stops referencing them.
- No data migration touches > 10k rows without batching.
- CI runs `upgrade head` then `downgrade base` then `upgrade head` on a scratch DB.

---

## Neo4j — graph model

### Node labels (canonical set; extensible)

| Label | Key property | Core properties |
|---|---|---|
| `:Tenant` | `tenant_id` | (anchor; every other node also carries `tenant_id`) |
| `:Identity` | `identity_id` | `kind` (user/service/machine), `name`, `first_seen`, `last_seen`, `risk` |
| `:Host` | `host_id` | `hostname`, `os`, `criticality`, `first_seen`, `last_seen` |
| `:IpAddress` | `ip` | `version`, `is_internal`, `geo_country`, `asn` |
| `:Domain` | `fqdn` | `registrar`, `first_seen`, `reputation` |
| `:Process` | `process_id` | `name`, `hash`, `signed`, `first_seen` |
| `:File` | `file_id` | `path`, `hash`, `first_seen` |
| `:Sensor` | `sensor_id` | `type` |
| `:Detection` | `detection_id` | `score`, `severity`, `created_at` (mirror key only; body in Postgres) |
| `:AttackChain` | `chain_id` | `stage_count`, `confidence`, `status` |
| `:AttackTechnique` | `technique_id` | `name`, `tactic` (knowledge graph) |
| `:ThreatActor` | `actor_id` | `name`, `aliases` (knowledge graph) |
| `:Campaign` | `campaign_id` | `name`, `first_seen`, `last_seen` (knowledge graph) |

Graph partition: `operational` vs `knowledge` distinguished by a `graph`
property (`'op'` | `'kg'`) and/or separate database on Neo4j Enterprise (U-003).

### Relationship types (canonical set; extensible)

`(:Identity)-[:AUTHENTICATED_TO {at, result, method}]->(:Host)`,
`(:Identity)-[:LOGGED_INTO {at, session_id}]->(:Host)`,
`(:Host)-[:CONNECTED_TO {at, port, bytes, proto}]->(:IpAddress)`,
`(:Host)-[:RESOLVED {at}]->(:Domain)`,
`(:Domain)-[:RESOLVES_TO {at}]->(:IpAddress)`,
`(:Host)-[:EXECUTED {at}]->(:Process)`,
`(:Process)-[:DOWNLOADED {at}]->(:File)`,
`(:Process)-[:SPAWNED {at}]->(:Process)`,
`(:Identity)-[:USED_CREDENTIAL_ON {at}]->(:Host)` (lateral movement),
`(:Detection)-[:INVOLVES]->(:Identity|:Host|:IpAddress|:Process|:Domain)`,
`(:AttackChain)-[:HAS_STAGE {order}]->(:Detection)`,
`(:AttackChain)-[:MAPPED_TO {confidence}]->(:AttackTechnique)`,
`(:Campaign)-[:INCLUDES]->(:AttackChain)`,
`(:ThreatActor)-[:ATTRIBUTED]->(:Campaign)`.

Relationships carry `tenant_id` + `observed_at`. Time-on-edge enables temporal
queries (req 12) without a separate temporal store.

### Constraints & indexes (migration `neo4j/0001`)

- `CREATE CONSTRAINT` uniqueness on every `*_id` key property per label, scoped
  with `tenant_id` where relevant (composite via a synthetic key or
  application-enforced + index).
- Range indexes on `observed_at` / `last_seen`.
- Full-text index on `Host.hostname`, `Domain.fqdn`, `Identity.name` for hunting.

### Graph invariants

- Every node and relationship has a non-null `tenant_id`.
- No relationship crosses `tenant_id`.
- Operational-graph nodes older than the retention window are pruned by a
  scheduled job (moved to knowledge graph only if referenced by a confirmed
  chain/campaign).
- `:Detection` node is a thin mirror — its authoritative body is Postgres
  `detection` with the same `detection_id`.

---

## Redis — key namespaces

See ADR-009 table. All keys `sm:`-prefixed; tenant-scoped values carry
`:<tenant_id>:` in the key. TTLs mandatory on every key except session (session
length) and fan-out streams (capped by `MAXLEN`).

---

## Retention (initial policy — revisited per tenant contract)

| Data | Store | Retention |
|---|---|---|
| raw telemetry | Kafka `telemetry.raw` | 7 days |
| canonical events | Kafka `events.canonical` | 30 days |
| detections | Postgres | 90 days hot, then archive to S3 (Parquet) |
| attack chains | Postgres + Neo4j | 180 days |
| operational graph | Neo4j | 30–90 days rolling (`SM` config) |
| knowledge graph | Neo4j | indefinite (curated) |
| audit log | Postgres | 365 days minimum, then S3 WORM |
| threat memory / campaigns | Postgres | indefinite (tenant-controlled) |
| reports | S3 | per template (default 365 days) |
