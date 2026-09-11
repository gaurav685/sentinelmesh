"""Report generation + retrieval. Internal-JWT only — role gating for
compliance reports (`lead`/`tenant_admin`) happens at the api-gateway BFF,
which holds the caller's role; this service trusts its caller's audience
check the same way every other internal service does.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field

from sm_common.errors import NotFound
from sm_common.security import InternalPrincipal
from sm_contracts import Report, ReportDownload, ReportKind, SmBaseModel, ThreatSubjectType

from ..deps import Services, get_generator, get_principal, get_repository, get_services
from ..generator import ReportGenerator
from ..repository import ReportRepository
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/reports", tags=["reports"])

#: A fresh presigned URL is minted on every read — never persisted, never
#: reused past its own expiry (ADR-019: time-limited, not a public bucket).
_DOWNLOAD_URL_TTL_SECONDS = 300


class CreateReportRequest(SmBaseModel):
    kind: ReportKind
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=200)
    requested_by: UUID


@router.post("", response_model=Report)
async def create_report(
    body: CreateReportRequest,
    principal: InternalPrincipal = Depends(get_principal),
    generator: ReportGenerator = Depends(get_generator),
) -> Report:
    return await generator.generate(
        principal.tenant_id, kind=body.kind, subject_type=body.subject_type.value,
        subject_id=body.subject_id, title=body.title, requested_by=body.requested_by,
    )


@router.get("/{report_id}", response_model=ReportDownload)
async def get_report(
    report_id: UUID,
    principal: InternalPrincipal = Depends(get_principal),
    repo: ReportRepository = Depends(get_repository),
    services: Services = Depends(get_services),
) -> ReportDownload:
    report = await repo.get(principal.tenant_id, report_id)
    if report is None:
        raise NotFound("report not found")
    download_url: str | None = None
    if report.storage_key is not None:
        download_url = await services.store.presigned_get_url(
            bucket=services.settings.s3_bucket_reports, key=report.storage_key,
            expires_in=_DOWNLOAD_URL_TTL_SECONDS,
        )
    return ReportDownload(report=report, download_url=download_url)
