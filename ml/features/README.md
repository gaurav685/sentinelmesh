# ml/features

Feature schemas live in code: `sm_ml.features` (`packages/ml-py`).

- `FEATURE_SCHEMA_VERSION` — bump on any change to a schema's feature set or
  ordering. A model trained on one version cannot consume another; every
  `Anomaly` row and every `ml/models/*/CONTRACT.md` records the version used.
- `FEATURE_SCHEMAS[kind]` — an ordered tuple of `FeatureSpec(name, lo, hi,
  description)` per `CanonicalKind`.
- `extract_features(canonical) -> FeatureVector` — a pure, deterministic function
  of the canonical event. No clock, no randomness, no I/O. Values are clamped to
  the schema range so a hostile event cannot push a feature to infinity.

Current version: **1** — `auth` (7), `network_flow` (8), `dns` (7),
`process_exec` (6), `file_access` (7).
