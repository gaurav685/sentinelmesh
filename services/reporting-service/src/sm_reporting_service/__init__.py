"""SentinelMesh threat reporting (req 22).

`POST /api/v1/reports` gathers content for one subject from
`detection-engine` (direct Postgres read — it has no read API of its own),
`graph-service`, `mitre-service`, `ai-analyst`, and `memory-service`
(internal HTTP), assembles a `Report` where every finding/recommendation/
timeline point carries a `GroundingKind` tier (evidence / inference /
prediction / synthetic — Constitution §3), renders it to PDF, and uploads
it to S3-compatible object storage (ADR-019). A content dependency that is
unreachable lands its section in `missing_sections` and the report as
`partial`; only an object-storage failure makes it `failed`. Produces
`report.generated`.

`GET /api/v1/reports/{id}` returns the report plus a fresh, time-limited
presigned download URL — never a public bucket, never a raw path a caller
could manipulate.
"""

from __future__ import annotations

from .app import build_services, create_app
from .version import API_PREFIX, API_VERSION, SERVICE_NAME, SERVICE_VERSION

__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "build_services",
    "create_app",
]
