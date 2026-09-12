# Deployment architecture

ADR-021. Docker Compose (local) has been real and running since Phase 1.
Kubernetes/Helm (production, Phase 16) has real, evidence-backed
verification against a real local `kind` cluster — see
`docs/architecture/kubernetes-deployment.md`'s "Verification status"
section for exactly what was and was not verified, and
`docs/IMPLEMENTATION_STATE.md`'s Phase 16 entry for the full evidence
trail. Nothing beyond what that section documents is claimed.

## Local (docker-compose) — Phase 1 authors this

`deploy/docker/docker-compose.yml` brings up:

| Service | Image (pin at authoring) | Purpose |
|---|---|---|
| `postgres` | postgres:16 | relational store |
| `neo4j` | neo4j:5-community | graph store (Phase ≥ 2 usage) |
| `redpanda` | redpandadata/redpanda | Kafka-API bus (Phase ≥ 2 usage) |
| `redis` | redis:7 | cache / sessions / rate limit |
| `minio` | minio/minio | S3-compatible object store |
| `keycloak` | quay.io/keycloak/keycloak | OIDC IdP (dev realm) |
| `prometheus` | prom/prometheus | metrics |
| `grafana` | grafana/grafana | dashboards |
| `mlflow` | (community image or built) | experiment tracking (Phase ≥ 5) |
| `app` | built from `deploy/docker/Dockerfile.app` | SentinelMesh in `monolith` profile |

Rules:

- **Container-to-container uses service names**, never `localhost`
  (`SM_PG_HOST=postgres`, `SM_KAFKA_BOOTSTRAP_SERVERS=redpanda:9092`, etc.).
- A `.env` file (from `.env.example`) is the single config source for compose.
- Healthchecks + `depends_on: condition: service_healthy` so `app` starts after
  its dependencies are ready.
- Named volumes for `postgres`, `neo4j`, `minio` data; all git-ignored.
- Phase 1 only needs `postgres`, `redis`, `keycloak`, `prometheus`, `grafana`,
  `app` to be functional; the rest are defined but not required until their
  phase.

External requirement: **Docker Desktop must be installed** to run this.

## Production (Kubernetes + Helm) — built in Phase 16

Real chart at `deploy/helm/sentinelmesh`; real namespace bootstrap at
`deploy/k8s/namespaces/namespaces.yaml`. Full detail (manifest inventory,
security posture, scaling strategy, backup/recovery, verification
status) is in `docs/architecture/kubernetes-deployment.md` — this section
stays as the original design summary.

- **Namespaces:** `sentinelmesh-system` (gateway, ingress, cert), `-data`
  (stateful: postgres/neo4j operators or managed endpoints, redis), `-bus`
  (kafka/redpanda), `-app` (stateless services), `-ml` (inference/training,
  GPU node pool), `-observability` (prometheus/grafana/loki/tempo/otel-collector).
- **Ingress:** single ingress → `api-gateway` + `notification-service` (WS).
  No other service is internet-facing.
- **NetworkPolicies:** default-deny per namespace; explicit allow only for the
  edges in `service-catalog.md`'s dependency graph + bus + datastores.
- **RBAC:** one ServiceAccount per service; least-privilege Roles; no service
  can read Secrets it does not own.
- **Secrets:** External Secrets Operator → Vault / cloud KMS. No plaintext
  Secrets in git or Helm values.
- **Probes:** `startupProbe` (slow deps), `livenessProbe` (`/healthz`),
  `readinessProbe` (`/readyz`, checks required deps).
- **Resources:** requests + limits on every container; JVM services (Flink) get
  heap-aware limits.
- **Autoscaling:** HPA on the stateless request path (CPU + custom: Kafka lag for
  consumers). Stateful sets are not autoscaled.
- **PodDisruptionBudgets** for every Deployment with replicas ≥ 2.
- **Rollout:** RollingUpdate `maxUnavailable=0 maxSurge=1`; readiness-gated;
  DB migrations run as a pre-upgrade `Job` (Helm hook) that must succeed first;
  migrations are backward-compatible so old + new pods coexist during rollout.
- **Storage:** PersistentVolumes for self-hosted stateful components; managed
  services preferred (RDS-class Postgres, managed Kafka).
- **Backup/recovery:** automated Postgres backups + PITR; Neo4j scheduled backup
  (Enterprise) or dump job (Community); S3 versioning; documented restore
  runbook + periodic restore test (a test, not a claim).
- **Observability:** OTel collector DaemonSet/Deployment; Prometheus + Grafana;
  Loki for logs; Tempo/Jaeger for traces; alert rules in `deploy/prometheus/`.

## Deployment profiles (ADR-003)

| Profile | Where | What runs |
|---|---|---|
| `monolith` | local, CI, small self-host | request-path services in one process; real Postgres/Redis/(Neo4j/Kafka when needed) |
| `distributed` | staging, production | every logical service independently, HPA, network policies |

The code is identical; only composition + config differ.
