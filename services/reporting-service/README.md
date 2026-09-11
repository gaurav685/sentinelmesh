# reporting-service

Threat reporting (requirement 22). Port 8013.

## Grounding, not fabrication

Every finding, recommendation, and timeline point in a report carries a
`GroundingKind` tier — `evidence` (a real detection/pattern), `inference`
(an ai-analyst-derived summary), `prediction` (a memory-service forecast),
or `synthetic` (simulation-sourced). A content dependency that is
unreachable while assembling a report lands its section name in
`missing_sections` and the report as a whole as `partial`; content is never
invented in its place. Only an object-storage failure (the PDF has nowhere
to go) makes a report `failed`.

## Content gathering

`POST /api/v1/reports` assembles a `Report` for one subject from every
dependency `docs/architecture/service-catalog.md` names:

- **`detection-engine`** — read directly from Postgres
  (`content_repository.py`). It exposes no internal read API of its own;
  this mirrors `api-gateway`'s own `SqlSocRepository`.
- **`graph-service`**, **`mitre-service`**, **`ai-analyst`**,
  **`memory-service`** — internal HTTP (`content_client.py`), each call
  minted a short-lived service token scoped to the target's audience and
  the tenant the report is being generated for.

`ai-analyst`'s grounded narrative (`/api/v1/analyst/explain`) is only
called when the report's subject *is* a detection — `ExplainRequest`'s
subject type has no host/ip/domain/identity variant.

## Rendering + storage

The assembled `Report` renders to PDF (`renderer.py`, `reportlab`) and
uploads to S3-compatible object storage (`sm_common.objectstore`,
ADR-019) under a per-tenant key prefix. `GET /api/v1/reports/{id}` returns
the report plus a fresh, 5-minute presigned download URL — never a public
bucket, never a raw path a caller could manipulate.

## Report templates

`report_template` (migration `0011`) seeds one default section list per
`ReportKind` (`incident` / `executive_summary` / `soc` / `compliance`). A
content dependency that a report kind's own template never asked for
(e.g. `executive_summary` has no `affected_assets` section) does not mark
that report `partial` if it happens to be unreachable.

## Not verified

- Report generation runs synchronously inside the `POST` request handler —
  there is no background worker pool yet (service-catalog names one as a
  future scaling path).
- Role-gating for compliance reports (`lead`/`tenant_admin`) is enforced at
  the api-gateway BFF, which holds the caller's role; this service trusts
  its caller's internal-JWT audience the same way every other internal
  service does.
- No accuracy claim for the `memory-service` lateral-movement prediction
  folded into `findings` — it is surfaced with its own `confidence` and
  `model_version`, tier `prediction`, exactly as `sm_ml.predict` produced
  it.
