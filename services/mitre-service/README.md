# mitre-service

MITRE ATT&CK technique/tactic catalog + a technique-mapping engine (req 7).
Port 8008. Health / metrics + the internal query API; no HTTP ingest.

## Catalog

Imported **offline** from a MITRE ATT&CK STIX 2.1 bundle. **No ATT&CK data ships
in this repository.**

```bash
python scripts/import_attack_stix.py --bundle ./enterprise-attack.json --version 14.1
```

`attack_matrix_version` records exactly what a run produced (counts +
`stix_bundle_sha256`). Until an import runs the catalog is empty, mapping returns
everything as `unmapped`, and `/readyz` carries an unhealthy `attack_catalog`
dependency.

## Mapping

`map_techniques` **validates + enriches** the candidate technique ids a detection
rule already named against the imported catalog — an unknown id is `unmapped`,
never guessed. A known id gets its name, tactic, and the matrix version.
`MappingSource.llm` is accepted via `/map` but never produced automatically and
never authoritative alone (ADR-014).

- Consumes `detections` and `attack_chains` (group `mitre-mapping`) → upserts
  `technique_mapping` rows (`source = rule`, `confidence = medium`; a detection's
  subject is `detection`, a chain's is `attack_chain`). Poison record →
  `<topic>.dlq`; a DB failure → retried.
- `GET /api/v1/mitre/techniques` — the catalog.
- `POST /api/v1/mitre/map` — `{subject_type, subject_id, technique_ids,
  rationale, source?, confidence?, persist?}` → matches + unmapped.
- `GET /api/v1/mitre/heatmap` — technique → distinct-subject counts, tenant
  scoped from the JWT.

All routes are internal, service-JWT (audience `mitre-service`).

## Run

```bash
python -m sm_mitre_service
```
