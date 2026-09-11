# simulation-service

Safe cyber simulation (requirements 16 / 17 / 26 / 35). Port 8011.

## Scenario execution

`POST /api/v1/sim/scenarios/run` runs one of `sm_ml.scenario`'s four templates
(`apt`, `ransomware`, `insider`, `brute_force`) against a **synthetic**
environment generated from the request's own seed — `sm_ml.scenario.validate_spec`
refuses any target that is not a synthetic (`sim-`-prefixed) id present in that
environment, before a single event is produced. This service never attacks a
real system and never can: there is no code path from a request to anything
outside the synthetic environment and (optionally) the `telemetry.raw` topic.

With `feed_pipeline: true`, every emitted event is also produced onto
`telemetry.raw` with `source.type = "simulation"` (`pipeline.py`), so a
simulation exercises the real normalization → detection → correlation → graph
pipeline — clearly labelled as a drill at every hop. With no event bus
configured, a `feed_pipeline` request is refused (422), not silently dropped.

## Deception

`POST /api/v1/deception/decoys` registers a decoy. `network_boundary` is a
closed set — `isolated` or `dmz-isolated` — **`'production'` is not a legal
value**, enforced both by the request schema and by a database `CHECK`
constraint, so a decoy can never be recorded as attached to production.
Decoys carry no credential field at all. Interactions are captured one-way
(`POST .../interactions`) — there is no endpoint that pushes anything from a
decoy back into another system. `DELETE .../decoys/{id}` tears a decoy down
(idempotent); its interaction history is kept for audit. A torn-down decoy
captures no further interactions.

## Config

`SM_EVENT_BUS_ENABLED` (optional — only needed for `feed_pipeline`), the usual
Postgres settings.

## Not verified

No decoy has been deployed against a real attacker; "deception event capture"
here means the HTTP capture path is real and tested, not that it has observed
genuine adversary behaviour.
