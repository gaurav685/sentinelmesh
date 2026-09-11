# memory-service

Threat memory (requirements 21 / 37). Port 8012.

## Three distinct record kinds, one store

`docs/ARCHITECTURE_DECISIONS.md` ADR-011 splits three stores across the
platform: the operational attack graph and the persistent knowledge graph
both live in Neo4j (`graph-service`); **threat memory** is Postgres +
pgvector, owned by this service, and never duplicates either graph or the
detection/chain tables in Postgres (`detection-engine` /
`correlation-engine`).

- **`ThreatMemory`** — a behavioral pattern per subject (identity/host/ip/
  domain/detection), upserted as its technique set grows. Never one row per
  occurrence — `occurrence_count` and `last_seen` track repetition.
- **`Campaign`** — a set of attack chains judged related by shared technique
  usage. `active -> dormant -> closed` on inactivity (the retention sweep).
- **`AdversaryFingerprint`** — one evolving fingerprint per subject, linking
  back to every campaign it has appeared in.

## Ingestion

Consumes `attack_chains` (group `memory`). The topic event is a thin
projection with no technique data, so the handler fetches the full chain from
`correlation-engine`'s internal read API (`GET /api/v1/chains/{id}`), reads
its aggregate `technique_ids`, and upserts a pattern, matches (or starts) a
campaign, and upserts a fingerprint — then produces `campaign.updates`.

## Similarity

`POST /api/v1/memory/similar` computes a deterministic
`sm_ml.memory.technique_feature_vector` for the query and orders candidates by
pgvector cosine distance. If the index or the extension is unavailable, the
repository falls back to a bounded (500-row), tenant-scoped Python scan using
`sm_ml.memory.cosine_similarity` — recomputed from each candidate's
`technique_ids`, not by reading the stored vector column back. Every
`SimilarityMatch` carries `exact_fallback` so a caller can tell which path
answered. **The raw feature vector is never part of any response.**

## Retention / deletion lifecycle

A background sweep (`SM_MEMORY_RETENTION_SWEEP_SECONDS`, default hourly) ages
an `active` campaign to `dormant` after `SM_MEMORY_DORMANT_AFTER_DAYS`
(default 14) of no new chains, to `closed` after
`SM_MEMORY_CLOSE_AFTER_DAYS` (default 60), and deletes patterns,
fingerprints, and closed campaigns whose `last_seen` is older than
`SM_MEMORY_RETENTION_DAYS` (default 180). A sweep failure is logged and
counted, never raised into a request.

## Not verified

No campaign-similarity threshold (`SM_MEMORY_CAMPAIGN_SIMILARITY_THRESHOLD`,
default 0.5) has been tuned against real attack data — it is a deterministic,
documented default, not a calibrated one. No accuracy or precision/recall
figure is claimed for campaign matching or fingerprint similarity.
