# Demo mode (Phase 18)

An isolated, synthetic, reproducible way to see the whole platform work
without any real telemetry, customer, or incident. Nothing in this section
is, or claims to be, a real attack, a real customer, or a real detection.

## What "demo mode" actually is

There is no separate "demo build" or feature flag that switches the
platform into a different code path. Demo mode is:

1. **A dedicated, clearly-labelled tenant** (`scripts/seed_demo.py`) —
   never named `default`, `production`, or anything that could be mistaken
   for a real organization. The tenant's `name` column literally says
   "SYNTHETIC DATA ONLY -- not a real organization" so it is unambiguous
   in every UI surface and every database row.
2. **`simulation-service`'s existing synthetic scenario engine**
   (Phase 12) — the same four deterministic, seeded scenario templates
   (`apt`, `ransomware`, `insider`, `brute_force`) already built for
   defensive stress-testing. Demo mode does not add a fifth thing; it is
   the intended, designed use of that engine, run by a human from the SOC
   UI instead of an automated red-team job.
3. **The real pipeline, opted into.** Every emitted event carries
   `simulated: true` unconditionally. Whether it also reaches the real
   Kafka topics (and therefore the real detection/graph/correlation
   pipeline) is a separate, explicit choice: `RunScenarioRequest.
   feed_pipeline` (default `false`). When `true`, `simulation-service`
   produces each event onto `telemetry.raw` with `source.type =
   "simulation"` — the same topic and schema real sensors use, so nothing
   downstream needs a "demo mode" branch of its own. Every service that
   ever touches the event can see `simulated: true` on it; none of them
   is authorized to strip that flag.

## Provisioning the demo tenant

```bash
python scripts/seed_demo.py                      # default placeholder password
python scripts/seed_demo.py --password 'something-else'
```

Idempotent — re-running updates the password and leaves everything else
alone. Creates:

| What | Value |
|---|---|
| Tenant slug | `demo-corp` |
| Tenant name | `SentinelMesh Demo Corp (SYNTHETIC DATA ONLY -- not a real organization)` |
| Admin email | `demo-admin@sentinelmesh.demo` |
| Admin role | `tenant_admin` (self-granted at bootstrap, since a brand-new tenant has no other user to grant it) |

This only provisions the *account*. It does not run a scenario or write
any telemetry — that is a separate, explicit action (below), so a freshly
seeded demo tenant starts with an empty graph and no alerts.

## Running a scenario

From the SOC UI's Simulation tab (after logging in as the demo admin), or
directly:

```bash
curl -s -c cookies.txt -D headers.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"tenant_slug":"demo-corp","email":"demo-admin@sentinelmesh.demo","password":"<password>"}' > /dev/null

CSRF=$(grep -i x-csrf-token headers.txt | awk '{print $2}' | tr -d '\r')

curl -s -b cookies.txt -X POST http://localhost:8000/api/v1/soc/simulation/run \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"name":"demo-run","kind":"brute_force","seed":7,"target_host":"sim-host-01","target_identity":"sim-id-alice","intensity":5,"feed_pipeline":true}'
```

`kind` is one of `apt`, `ransomware`, `insider`, `brute_force`. `seed`
makes the run reproducible -- the same seed always produces the same
synthetic environment and the same events.

`feed_pipeline: true` requires `SM_EVENT_BUS_ENABLED=true` (and the `bus`
compose profile) on `ingestion-gateway` **and** `simulation-service` --
both default to `false` so either service can run without Kafka present.
Requesting it with the bus disabled is refused with a real 4xx, not a
silent no-op: `"feed_pipeline requires the event bus, which is disabled
on this deployment"`.

## Verified real end-to-end (2026-09-16, local docker-compose, evidence below)

With `SM_EVENT_BUS_ENABLED=true` and the `bus`/`graph`/`detect` profiles
running, a real `brute_force` run (`intensity=5`, 31 events,
`feed_pipeline=true`) was traced through every real hop by reading each
service's own Prometheus counters and the real Postgres/Neo4j rows they
wrote -- not by trusting the API response alone:

| Hop | Real evidence |
|---|---|
| `simulation-service` → `telemetry.raw` | API response: `fed_to_pipeline: true, fed_event_count: 31` |
| `ingestion-gateway` → `normalization-engine` | `sm_consumer_records_total{topic="telemetry.raw"}` incremented by the run |
| `normalization-engine` → `events.canonical` | consumed and re-published; `stream-processor`'s own consumer counter for `events.canonical` incremented |
| `stream-processor` → `graph.commands` | `graph-service`'s consumer counter for `graph.commands` incremented |
| `graph-service` → Neo4j | `MATCH (n) WHERE n.tenant_id IS NOT NULL RETURN count(n)` grew (116 nodes present after several runs) |
| `detection-engine` consuming `events.canonical` | its own consumer counter incremented by the same event count |
| real rule detector firing | Postgres `detection` table: one real row, `detector=rule`, `rule_id=rule.auth.failed_burst`, `technique_ids=["T1110"]`, real evidence array with `provenance` fields pointing at the actual normalization-engine/detection-engine event ids |
| correlation → attack chain | Postgres `attack_chain` table: one real row |
| SOC API | `GET /api/v1/soc/detections` returns that exact detection with its full evidence chain, tenant-scoped to `demo-corp` |

**Real, honest gap found and left undisguised:** an earlier `apt` run (23
events, `feed_pipeline=true`) was consumed by every hop above the same
way (confirmed via the same counters) but produced **zero** rows in
`detection` or `attack_chain`. `detection-engine`'s ML path
(`isolation_forest_file_access` via `ml-inference`) returned a real `503`
because that model has no artifact deployed to this local stack --
matching the documented, intentional "503 when a named model artifact is
missing, never a fabricated score" behavior (`services/ml-inference`).
Its rule-based path evaluated the same 23 events and found no rule match
-- the current stateful rule detectors are volume/threshold-based
(`rule.auth.failed_burst` needs a burst of failures within a window);
the `apt` template's narrative, low-volume, single-shot events do not
reach any existing rule's threshold at `intensity=4`. This is not a bug
in the demo path -- it is a real, currently-existing gap in detection
*coverage* (no rule or trained model targets the `apt`/`ransomware`/
`insider` templates' specific patterns), and is recorded here rather than
hidden behind "the demo works." `brute_force` is the one scenario kind
confirmed, with real evidence, to reliably produce a real detection at
demo intensities.

## Known limitation: interactive OIDC/SSO browser login is NOT VERIFIED

`scripts/seed_demo.py`'s local email/password login (above) is real,
end-to-end verified. A separate path also exists to log in via Keycloak
(the SOC UI's SSO option / `GET /api/v1/auth/oidc/login?tenant=<slug>`) --
this one is `NOT VERIFIED — REQUIRES A REVERSE PROXY OR MATCHING DNS`, and
was found, investigated, and deliberately left unresolved rather than
half-fixed into a less secure state:

Every service validates that Keycloak's own OIDC discovery document
(`/.well-known/openid-configuration`) reports an `issuer` exactly matching
`SM_OIDC_ISSUER` -- a real, intentional security check against issuer
confusion, not incidental. `SM_OIDC_ISSUER` is `http://keycloak:8080/...`
(the only address containers can reach Keycloak at). Setting Keycloak's
own `KC_HOSTNAME=localhost` (tried during this phase, so the *browser*
could follow the login redirect) makes Keycloak advertise
`http://localhost:8080/...` as its `issuer` too, not just the redirect
target -- which then fails that same check for every internal service.
Keycloak cannot be given two different self-identities (one the
container network resolves, one the browser resolves) without a reverse
proxy or shared DNS name in front of it, and this local `docker-compose`
stack has neither. A real Kubernetes/production deployment behind a real
ingress would not have this problem, since both the browser and the
cluster's internal traffic resolve the same public hostname.

## Isolation guarantees (carried over from Phase 12, re-verified here)

- `production` is not a legal value for a simulation/deception scope at
  the schema **or** database level -- there is no code path from a
  synthetic scenario into anything that could touch real infrastructure.
- Every emitted event and every stored decoy/interaction row carries
  `simulated: true` (or the deception equivalent) and this repository has
  no code path that clears that flag once set.
- The demo tenant is a normal tenant under the same RBAC/tenant-isolation
  rules as any other -- it gets no special code path, no bypass, and no
  elevated trust. It is different from a real tenant only in what a human
  chose to name it and log into it as.

## What demo mode is never allowed to claim

Per the Phase 18 instruction, and enforced by the `simulated`/`synthetic`
flags above, nothing produced by a demo run may be presented, logged, or
reported as: a real attack, a real customer, real telemetry, real threat
intelligence, or a real incident. The SOC UI badges every simulation
surface "SIMULATION" (Phase 12); this document is the same rule applied
to the backend evidence trail.
