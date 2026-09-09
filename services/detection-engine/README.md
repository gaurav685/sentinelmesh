# detection-engine

`telemetry → features → anomaly score → evidence → detection → alert` (req 5).

Consumes `events.canonical` (group `detection`). System of record for Postgres
`detection` / `anomaly` / `security_alert`. Emits `detections`. `threat_score` is
written by `correlation-engine` (Phase 7), which sees the whole attack chain.
Port 8006. Health / metrics only — no HTTP ingest.

## Pipeline per event

1. `sm_ml.extract_features` — deterministic feature vector for the canonical kind.
2. **Statistical anomaly** — a `StatisticalModel` (MAD z-score) is refit on every
   event from a per-`(tenant, kind)` rolling window of the last
   `SM_DETECTION_WINDOW_SIZE` vectors, once it has `SM_DETECTION_MIN_SAMPLES`
   (adaptive thresholds). Writes an `anomaly` row.
3. **Trained model** (optional) — `POST ml-inference /infer/{model}`. Any failure
   (unreachable / 503 `MODEL_UNAVAILABLE` / timeout) → the contribution is
   dropped and `scoring_status = DEGRADED` (ADR-013). Never a dropped detection,
   never a fabricated score.
4. **Rules** — deterministic indicators over the event + features + a
   time-bounded timeline: repeated auth failures, credential reuse across hosts,
   auth-then-large-egress (lateral movement), unsigned process with an unusual
   command line, DNS tunnelling characteristics, NXDOMAIN burst. A rule states a
   fact; MITRE technique ids are *candidates* for Phase 6, not assertions.
5. **Composite score** — a fixed, versioned weighting (`WEIGHTS_VERSION`) over
   the `rule` / `statistical` / `model` components; a missing component is
   dropped and the rest renormalised. Deterministic and reproducible.
6. **Detection** — written only when a rule fired at `medium`+ or the composite
   score crossed `SM_DETECTION_SCORE_THRESHOLD`. Deterministic id
   (`detection_id_for(dedup_key, day)`) so a reprocess updates, not duplicates.
   Every claim is an `EvidenceItem` with a `provenance`.
7. **Alert** — at `high`/`critical` or score ≥ `SM_DETECTION_ALERT_THRESHOLD`,
   one `security_alert` per detection.
8. **Emit** — a thin `DetectionPayload` on `detections`.

Malformed record / unknown kind → `graph`… → `events.canonical.dlq`. A DB write
or produce failure → retried.

## No claims

No accuracy, F1, precision, recall, latency or throughput figure is produced or
stored. The rolling window is in-process and bounded (Redis-backed shared windows
are the scale path and do not change the contract).

## Run

```bash
python -m sm_detection_engine
```
