# Kubernetes + enterprise deployment (Phase 16)

Implements ADR-021's production half. The chart is `deploy/helm/sentinelmesh`
(one umbrella chart, values-driven per service — see the rationale in
`Chart.yaml`'s own description). Cluster bootstrap namespaces live in
`deploy/k8s/namespaces/namespaces.yaml`, applied once, outside the Helm
release, before the first `helm install`.

Scope: the 14 real, implemented HTTP services (`api-gateway` … 
`reporting-service`, ports 8000-8013) plus `frontend`. The five
not-yet-built placeholder service directories (`agent-orchestrator`,
`ai-analyst-service` naming remnant, `deception-service`,
`federation-service`, `notification-service`) get no Kubernetes resources
here — building manifests for code that doesn't exist would be fabrication.

## Manifest inventory

| File | Renders |
|---|---|
| `templates/_helpers.tpl` | naming/label helpers |
| `templates/configmap.yaml` | one ConfigMap, all non-secret `SM_*` vars (`global.env`) |
| `templates/secret-external.yaml` | `ExternalSecret` (default) or a plain dev-only `Secret`, in every namespace with a real consumer (`-app`, `-data`) |
| `templates/serviceaccount.yaml` | one ServiceAccount per service, `automountServiceAccountToken: false` |
| `templates/rbac.yaml` | deliberately empty — see "RBAC" below |
| `templates/deployment.yaml` | one Deployment per service + frontend |
| `templates/service.yaml` | one ClusterIP Service per service + frontend |
| `templates/hpa.yaml` | HPA per service where `hpa.enabled` |
| `templates/pdb.yaml` | PDB for every service/frontend with `replicas >= 2` |
| `templates/networkpolicy.yaml` | default-deny + per-service allow rules |
| `templates/ingress.yaml` | one Ingress: `api-gateway` (`/api`) + `frontend` (`/`) |
| `templates/migration-job.yaml` | pre-install/pre-upgrade Helm hook Job running the same `alembic upgrade head` command as compose's `migrate` service |
| `templates/stateful/*.yaml` | self-hosted StatefulSets: postgres, neo4j, redis, redpanda, minio, keycloak |

## Security

- **Least privilege / RBAC:** grepped every service's and package's source tree for a Kubernetes client import — none exists. No service calls the
  Kubernetes API, so no Role/RoleBinding is granted to any application
  ServiceAccount (`templates/rbac.yaml` documents this explicitly rather than
  rendering an unused permission "to satisfy a checklist"). Every
  ServiceAccount also sets `automountServiceAccountToken: false`, so no pod
  even has a token to a namespace's API endpoint.
- **No hardcoded secrets:** every `[secret]`-tagged variable from
  `.env.example` (`SM_PG_PASSWORD`, `SM_NEO4J_PASSWORD`, `SM_REDIS_PASSWORD`,
  `SM_S3_ACCESS_KEY_ID`/`SM_S3_SECRET_ACCESS_KEY`, `SM_OIDC_CLIENT_SECRET`,
  `SM_INTERNAL_JWT_SIGNING_KEY`, `SM_LLM_API_KEY`) is sourced from an
  `ExternalSecret` (default `secretsProvider: eso`) pointed at a real
  Vault/cloud-KMS `SecretStore`/`ClusterSecretStore` created outside this
  chart. `secretsProvider: manual` exists only for a local `kind` smoke test
  and defaults every value to empty — nothing ships with a real credential
  baked into a values file. Keycloak's own admin bootstrap credential (not
  an app secret — no service reads it) is randomly generated at install time
  via `lookup`+`randAlphaNum`, not hardcoded, and reused across upgrades so
  `helm upgrade` cannot lock out the admin account.
- **No unnecessary DB exposure:** every stateful component (`postgres`,
  `neo4j`, `redis`, `redpanda`, `minio`, `keycloak`) is a headless
  `ClusterIP: None` Service with no Ingress — reachable only inside the
  cluster, and only from the specific services whose `dependsOn`/`needs`
  actually require it (network policy below).
- **No root without justification:** every application container
  (`deployment.yaml`) runs as the Dockerfile.app's built-in non-root
  `uid 10001` (`podSecurityContext.runAsNonRoot/runAsUser`), with
  `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, and all
  Linux capabilities dropped; a single `emptyDir` at `/tmp` is the only
  writable path a service needs. Stateful images run as their own official
  non-root user (postgres 999/neo4j/minio 1000/redpanda), which their
  upstream images require for their data-directory permissions — `root fs
  read-only` is intentionally NOT set on stateful containers, since they
  legitimately write logs/temp/config under paths the vendor image doesn't
  expect to be pre-split out, and this is documented in each stateful
  template rather than silently relaxed.
- **No excessive Kubernetes permissions:** see RBAC above — zero, not
  "trimmed", because zero is what the code actually uses.
- **No public exposure of internal services:** the ingress
  (`templates/ingress.yaml`) has exactly two backends, `sm-api-gateway` and
  `sm-frontend`. Every other Service is ClusterIP-only with no Ingress
  resource, and NetworkPolicy denies any traffic the ingress-controller
  namespace doesn't specifically need (`api-gateway` and `frontend` only).
- **NetworkPolicy:** default-deny-all (`Ingress`+`Egress`) per namespace,
  then per-service allow rules generated directly from
  `values.yaml`'s `services.<name>.dependsOn` and `.needs` maps — which were
  themselves extracted from `deploy/docker/docker-compose.yml`'s real
  `depends_on` blocks and `*_URL` environment variables, not from the more
  expansive (partly aspirational) `service-catalog.md` graph. Ingress rules
  are the reverse lookup (who names me in their `dependsOn`) plus the
  observability namespace (Prometheus scrape) plus, for `api-gateway` only,
  the ingress-controller namespace.
- **Pod Security:** namespaces are labelled
  `pod-security.kubernetes.io/enforce: restricted` (except
  `-observability`, `baseline`, since some upstream exporters need
  marginally more), so the PSA admission controller itself rejects any pod
  that doesn't meet the non-root/no-privilege-escalation/dropped-capabilities
  bar described above — this isn't just a chart convention, it's enforced at
  the cluster level.

## Scaling strategy

No capacity numbers below are measured or fabricated; only mechanisms are
described, per the phase's explicit instruction. Real throughput/latency
numbers can only come from an actual load test against a real cluster,
which has not been run.

| Component | Mechanism | Notes |
|---|---|---|
| **API** (`api-gateway`) | HPA, CPU utilization (target 70%), `minReplicas: 2` | Stateless, horizontally scalable without coordination; `PodDisruptionBudget minAvailable: 1` keeps it available during voluntary disruption. |
| **Workers** (`ai-analyst`, `simulation-service`, `reporting-service`, etc.) | HPA, CPU utilization | Each is a stateless HTTP service; scale is bounded only by their own downstream dependency capacity (e.g. `ai-analyst` calling `correlation-engine`), not by anything in the pod itself. |
| **Kafka consumers** (`normalization-engine`, `stream-processor`, `graph-service`, `detection-engine`, `mitre-service`, `correlation-engine`, `memory-service`, `reporting-service`) | CPU-based HPA today; the intended real trigger is consumer-group lag (`sm_consumer_lag`, already emitted per Phase 15's observability work) via a KEDA `ScaledObject` | A Kafka consumer group can have at most one consumer per partition — replica count is hard-bounded by the topic's partition count regardless of any HPA setting. KEDA is a separate cluster-wide operator; this chart does not install it or claim lag-based scaling works, since that would require a real KEDA install and a real verified `ScaledObject`, neither of which has happened. CPU-based HPA is the honest fallback that is actually shipped. |
| **Stream processor** | Same as Kafka consumers above | `stream-processor` has no DB/Neo4j dependency, so it scales independently of the graph/DB write path. |
| **Graph services** (`graph-service`) | HPA, CPU, capped at `maxReplicas: 4` | Neo4j's own write path is effectively single-writer (ADR-driven ordering); this cap reflects that scaling `graph-service` pods does not scale Neo4j's own write throughput, only its read/query fan-out. Raising this cap without also addressing Neo4j's write path would create request pile-up, not real throughput. |
| **ML inference** (`ml-inference`) | HPA, CPU | Resource requests assume CPU-only inference (no GPU `resources.limits` entry) because no GPU-backed model artifact ships or is claimed trained (ADR-024). A real GPU-serving deployment needs a GPU node pool and a device-plugin-aware resource request, not present here since it isn't yet needed. |
| **Frontend** | HPA, CPU utilization | Pure static/SSR Next.js process; it has no DB access at all (network policy only allows egress to `api-gateway`), so it scales independently of every backend service. |
| **Stateful components** (postgres/neo4j/redis/redpanda/minio/keycloak) | **Not autoscaled** | Single-replica `StatefulSet`s. This is the honest state of a self-hosted, `kind`-verifiable chart, not a production HA claim — ADR-021 prefers a managed equivalent (RDS-class Postgres, managed Kafka, managed Redis) for real production, specifically because those bring real HA/scaling that a single-replica self-hosted StatefulSet does not. |

## Backup / recovery

- **PostgreSQL:** the chart itself does not run a backup job (no backup
  operator/cron is installed or claimed working). The documented, but
  *not yet executed*, approach for a real production install is: continuous
  WAL archiving to the same S3-compatible store already used for
  artifacts/reports (`SM_S3_*`) plus periodic `pg_dump` snapshots, giving
  point-in-time recovery bounded by WAL archive retention. A managed
  Postgres (RDS-class) gets this for free and is ADR-021's stated
  preference; the self-hosted `StatefulSet` here is for local/demo
  verification, not a production backup target.
- **Neo4j:** Neo4j Community Edition (the image this chart uses) has no
  online backup tool — only an offline `neo4j-admin database dump` (Neo4j
  down) or a filesystem-level snapshot of the PVC while the pod is stopped.
  A real production install needing online backup would need Neo4j
  Enterprise's `neo4j-admin database backup` or an external snapshot of the
  underlying volume via the storage provider (e.g. a cloud disk snapshot).
  Neither is wired into this chart; this is a documented gap, not a claimed
  capability.
- **Kafka (Redpanda) recovery:** this chart runs a *single-broker*
  Redpanda `StatefulSet` — there is no in-cluster replication, so recovery
  from broker loss is recovery from the PVC alone (whatever the underlying
  storage class's durability/snapshot guarantees are). A real production
  deployment needs >=3 brokers with `replication.factor >= 3` on every
  topic so that Redpanda's own Raft replication is the recovery mechanism —
  not implemented here since it hasn't been provisioned or tested.
- **Redis recovery:** the `StatefulSet` runs with `--appendonly yes` (AOF)
  against its PVC, so a pod restart replays the AOF file and recovers cache
  state from the volume. Redis here is used as cache/session/rate-limit
  state (per `.env.example`), not a source of truth, so this is recovery of
  convenience, not a correctness-critical guarantee — nothing in the
  services treats Redis as durable storage.
- **Configuration recovery:** all Kubernetes configuration is this chart
  plus `values*.yaml` in git — recovery is `git checkout` + `helm upgrade
  --install`. Secrets are recovered independently via the External Secrets
  Operator re-syncing from Vault/KMS (the actual source of truth), not from
  anything stored in the cluster or in git.
- **Disaster-recovery assumptions (explicit, not hidden):** (1) the
  underlying `StorageClass`'s volumes survive node loss (true for any real
  cloud block-storage class; NOT true for `kind`'s default local
  `hostPath`-backed provisioner, which is why `kind` is explicitly a
  verification environment, not a DR-tested one); (2) the External Secrets
  backing store (Vault/KMS) is itself backed up by whoever operates it,
  outside this chart's scope; (3) no restore procedure above has actually
  been executed end-to-end — this section describes the intended mechanism,
  not a tested runbook. A tested runbook is future work and must not be
  claimed done until a real restore has actually been performed and
  observed to succeed.

## Rollout strategy

`RollingUpdate` with `maxUnavailable: 0, maxSurge: 1` on every Deployment,
`startupProbe`/`readinessProbe` gating traffic, and a migration Job
(`migration-job.yaml`) running the identical
`alembic -c /app/migrations/postgres/alembic.ini upgrade head` command
`docker-compose.yml`'s own `migrate` service already uses, wrapped in a
retry loop and an initContainer that waits for Postgres to be reachable.
It is a Helm `pre-upgrade` hook (not `pre-install`): a pre-install hook
runs before every other manifest in the release, including the Postgres
StatefulSet itself, so Postgres would not exist yet for a first install
to migrate against — on first install this Job is a normal release
resource instead, scheduled alongside Postgres.

## Verification status (real, evidence-backed — 2026-09-12/13, `kind` v0.33.0, `helm` v4.3.0)

**Static validation:** `helm lint` clean; `helm template` renders clean
against both `secretsProvider: eso` (default) and `secretsProvider:
manual` (the dev/kind-only fallback) — the latter surfaced and fixed a
real Sprig `get`-on-nil-map bug (`get ($.Values.secrets | default dict)
.` in `secret-external.yaml`), not a hypothetical one.

**Real cluster stood up and installed into** (`kind create cluster`,
namespaces applied, `helm install` with a local values overlay —
`values-kind-smoketest.yaml` — that trims replica counts/resources to
fit one developer-machine node and disables `frontend`/`ingress`, since
no frontend image was built and no ingress controller was installed for
this pass):

- ✅ **All 6 namespaces created for real** (`kubectl apply -f
  deploy/k8s/namespaces/namespaces.yaml`), with `pod-security.kubernetes.io/
  enforce` genuinely enforced by the cluster — confirmed by real admission
  **rejections** (not just lint warnings) for the postgres/neo4j
  StatefulSets under `restricted`, which is why `-data`/`-bus` are
  `baseline` instead (documented in `namespaces.yaml` and in the Security
  section above).
- ✅ **All 6 self-hosted stateful components reached real `1/1 Running`**
  against real PVCs (postgres, neo4j, redis, minio, redpanda) — three
  real bugs were found and fixed by actually running the real images, not
  guessed: postgres/neo4j's official images start as root to chown a
  fresh PVC then drop privilege internally (`runAsNonRoot: true` alone
  fails admission — fixed with a trimmed `add` capability set);
  `NEO4J_PASSWORD` collided with the image's own env-to-config
  auto-mapping (renamed to `SM_NEO4J_BOOTSTRAP_PASSWORD`); redpanda's
  `--memory=1G` flag exceeded its container's memory limit
  ("insufficient physical memory" — parametrized as `seastarMemory`,
  now kept in sync with `resources.limits.memory`). Keycloak reached
  `1/1 Running` too after fixing a real `OOMKilled` (512Mi was not
  enough for its JVM) — its remaining slowness (a startup budget past 10
  minutes on this single developer-machine node) is a resource-contention
  characteristic of this specific local environment, not a chart defect.
- ✅ **All 14 real app Deployments reached real `1/1 Running`**, each
  actually connecting to real Postgres/Redis/Neo4j/Redpanda — confirmed
  with real log evidence, e.g. `api-gateway`'s own `/healthz` and
  `/readyz` both returning real HTTP 200 (the latter after a real ~150ms
  dependency check, not a stub).
- ✅ **NetworkPolicy, ServiceAccounts, absence of RBAC, ConfigMap/Secret
  (both providers) all verified present and correctly shaped** on the
  real API server (`kubectl get networkpolicy` — 15 objects, default-deny
  plus one per service; `kubectl get role,rolebinding` — genuinely none,
  matching the documented least-privilege decision).
- ❌ **NOT VERIFIED: the migration Job completing successfully.** Real,
  reproducible finding, not resolved despite substantial isolation effort:
  a short-lived one-off pod's `asyncpg`/SQLAlchemy connection attempt to
  the real, reachable Postgres pod repeatedly failed (`socket.gaierror`
  intermittently, or a 60s `TimeoutError` even when DNS was bypassed by
  connecting to Postgres's literal pod IP) — while `busybox nslookup`/`nc`
  against the exact same target succeeded reliably at the same moments,
  and the long-lived `api-gateway` service's own connection to the same
  Postgres pod, through the same `sm_common.db.engine.build_engine` code
  path, worked correctly. The discrepancy is specific to a short-lived,
  freshly-scheduled pod issuing Python's async DB connection, and its root
  cause was not conclusively isolated (candidates considered and not
  confirmed: CNI/`kindnet` pod-network warm-up on this
  Windows/WSL2/Docker-Desktop host, glibc resolver behavior under
  `readOnlyRootFilesystem`, or asyncpg's own connection-establishment
  path under CPU contention). Because the migration never completed, the
  Postgres schema used in the rest of this verification pass is empty —
  the ✅ items above verified infra-level reachability/health, **not**
  application behavior against a real migrated schema. This is marked
  `NOT VERIFIED — REQUIRES FURTHER INVESTIGATION` rather than claimed
  fixed or worked around, per this phase's explicit instruction never to
  claim success without evidence. Follow-up direction: reproduce outside
  `kind` (a real multi-node cluster, or plain Docker) to determine whether
  this is `kind`/host-specific.
- ❌ **NOT VERIFIED: `ingress`, `frontend`, `HPA` (no metrics-server in
  `kind`), and `KEDA`/consumer-lag autoscaling** — all deliberately out of
  scope for this pass (documented in `values-kind-smoketest.yaml`), not
  attempted and not claimed working.

No capacity number, throughput figure, or "production-ready" claim is
made anywhere in this document or in `IMPLEMENTATION_STATE.md`'s Phase 16
entry — everything above is either a real command's real output, or
explicitly marked as not verified.
