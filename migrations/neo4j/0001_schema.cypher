// SentinelMesh graph schema — migration 0001.
// Authority: docs/architecture/data-model.md "Neo4j — graph model".
//
// Runner: scripts/graph_migrate.py (sm_common.graph.migrate). Each ";"-terminated
// statement runs in its own auto-commit transaction; "//" lines are comments.
// Every statement is IF NOT EXISTS, so re-running is a no-op.
//
// Per-tenant uniqueness: Neo4j Community has only single-property uniqueness
// constraints (composite NODE KEY is Enterprise). data-model.md permits "a
// synthetic key" — so graph-service writes a `uid` property
// `"<tenant_id>:<natural_key>"` on every node and this migration puts a UNIQUE
// constraint on it. The natural key (`host_id`, `ip`, ...) plus `tenant_id`
// stay as their own properties and get a composite range index for lookups.

// --- node uniqueness: synthetic per-tenant key -----------------------------
CREATE CONSTRAINT tenant_uid    IF NOT EXISTS FOR (n:Tenant)          REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT identity_uid  IF NOT EXISTS FOR (n:Identity)        REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT host_uid      IF NOT EXISTS FOR (n:Host)            REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT ip_uid        IF NOT EXISTS FOR (n:IpAddress)       REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT domain_uid    IF NOT EXISTS FOR (n:Domain)          REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT process_uid   IF NOT EXISTS FOR (n:Process)         REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT file_uid      IF NOT EXISTS FOR (n:File)            REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT sensor_uid    IF NOT EXISTS FOR (n:Sensor)          REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT detection_uid IF NOT EXISTS FOR (n:Detection)       REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT chain_uid     IF NOT EXISTS FOR (n:AttackChain)     REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT technique_uid IF NOT EXISTS FOR (n:AttackTechnique) REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT actor_uid     IF NOT EXISTS FOR (n:ThreatActor)     REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT campaign_uid  IF NOT EXISTS FOR (n:Campaign)        REQUIRE n.uid IS UNIQUE;

// --- graph-command idempotency ledger (Phase 4 Unit 2) --------------------
CREATE CONSTRAINT graph_command_id IF NOT EXISTS FOR (c:_GraphCommand) REQUIRE c.command_id IS UNIQUE;

// --- schema-migration ledger --------------------------------------------
CREATE CONSTRAINT graph_migration_version IF NOT EXISTS FOR (m:_GraphMigration) REQUIRE m.version IS UNIQUE;

// --- tenant-scoped natural-key lookup indexes ---------------------------
CREATE INDEX identity_key   IF NOT EXISTS FOR (n:Identity)        ON (n.tenant_id, n.identity_id);
CREATE INDEX host_key       IF NOT EXISTS FOR (n:Host)            ON (n.tenant_id, n.host_id);
CREATE INDEX ip_key         IF NOT EXISTS FOR (n:IpAddress)       ON (n.tenant_id, n.ip);
CREATE INDEX domain_key     IF NOT EXISTS FOR (n:Domain)          ON (n.tenant_id, n.fqdn);
CREATE INDEX process_key    IF NOT EXISTS FOR (n:Process)         ON (n.tenant_id, n.process_id);
CREATE INDEX file_key       IF NOT EXISTS FOR (n:File)            ON (n.tenant_id, n.file_id);
CREATE INDEX sensor_key     IF NOT EXISTS FOR (n:Sensor)          ON (n.tenant_id, n.sensor_id);
CREATE INDEX detection_key  IF NOT EXISTS FOR (n:Detection)       ON (n.tenant_id, n.detection_id);
CREATE INDEX chain_key      IF NOT EXISTS FOR (n:AttackChain)     ON (n.tenant_id, n.chain_id);
CREATE INDEX technique_key  IF NOT EXISTS FOR (n:AttackTechnique) ON (n.tenant_id, n.technique_id);
CREATE INDEX actor_key      IF NOT EXISTS FOR (n:ThreatActor)     ON (n.tenant_id, n.actor_id);
CREATE INDEX campaign_key   IF NOT EXISTS FOR (n:Campaign)        ON (n.tenant_id, n.campaign_id);

// --- temporal indexes (data-model.md: "Range indexes on observed_at / last_seen") ---
CREATE INDEX identity_last_seen IF NOT EXISTS FOR (n:Identity) ON (n.last_seen);
CREATE INDEX host_last_seen     IF NOT EXISTS FOR (n:Host)     ON (n.last_seen);
CREATE INDEX campaign_last_seen IF NOT EXISTS FOR (n:Campaign) ON (n.last_seen);
CREATE INDEX authenticated_to_at IF NOT EXISTS FOR ()-[r:AUTHENTICATED_TO]-() ON (r.observed_at);
CREATE INDEX logged_into_at      IF NOT EXISTS FOR ()-[r:LOGGED_INTO]-()      ON (r.observed_at);
CREATE INDEX connected_to_at     IF NOT EXISTS FOR ()-[r:CONNECTED_TO]-()     ON (r.observed_at);

// --- full-text indexes for hunting (data-model.md) ---------------------
CREATE FULLTEXT INDEX host_search     IF NOT EXISTS FOR (n:Host)     ON EACH [n.hostname];
CREATE FULLTEXT INDEX domain_search   IF NOT EXISTS FOR (n:Domain)   ON EACH [n.fqdn];
CREATE FULLTEXT INDEX identity_search IF NOT EXISTS FOR (n:Identity) ON EACH [n.name];
