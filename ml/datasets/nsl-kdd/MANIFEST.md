# Dataset manifest — NSL-KDD

Follows `docs/REQUIREMENTS_TRACEABILITY.md` R24. No dataset file ships in this
repository (ADR-024) — this manifest describes the format the adapter
(`sm_ml_training.benchmark.nsl_kdd`) reads, not a shipped artifact.

```
dataset_id:       nsl-kdd
source:           NSL-KDD (University of New Brunswick, a de-duplicated,
                  rebalanced revision of KDD Cup 1999)
license:          research use; redistribute per the original distributor's terms
staging:          $SM_DATASET_ROOT/archive/{KDDTrain+.txt,KDDTest+.txt}
                  (this repo's own staging convention — the upstream
                  distribution ships as plain-text KDDTrain+.txt / KDDTest+.txt,
                  no header row)
format:           comma-separated, one connection record per line, no header
columns:          42 total —
                    0-40  the 41 standard KDD features (duration, protocol_type,
                          service, flag, src_bytes, dst_bytes, ... same_srv_rate,
                          dst_host_srv_rerror_rate) — see the original KDD Cup
                          1999 documentation for the full 41-column definition
                    41    attack_type (string; "normal" or an attack name, e.g.
                          "neptune", "smurf")
                    42    difficulty (int; NSL-KDD's own per-record difficulty
                          score — not used by this adapter)
label:            0 (benign) if attack_type == "normal", else 1 (attack) —
                  binary anomaly-detection framing, not the multi-class attack
                  taxonomy (matches sm_ml.models.AnomalyModel's binary contract)
categorical cols: indices 1 (protocol_type), 2 (service), 3 (flag) — one-hot
                  encoded against a vocabulary DERIVED FROM THE TRAIN SPLIT
                  ITSELF (sorted, deterministic), with an explicit "unknown"
                  bucket for a category the test split has that train did not —
                  never a hardcoded vocabulary that risks silently missing a
                  real category value
numeric cols:     the remaining 38 columns, used as-is (float)
preprocessing_version: "nsl-kdd-v1" (bumped if the encoding scheme changes —
                  a benchmark result records this string so a later adapter
                  change cannot silently make an old result incomparable)
```

## Verification method

`sm_ml_training.benchmark.harness.run_benchmark` fits/evaluates a real
`sm_ml.models` implementation against the real file and reports the sha256 of
both files read, so a result can be checked against the exact bytes evaluated.
**No metric exists until that function is actually run against a real,
locally-staged copy of the file** — nothing here or in code fabricates one.
