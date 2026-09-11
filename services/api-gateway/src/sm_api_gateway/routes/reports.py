"""Reporting + attack-storytelling BFF (Phase 14) — the browser-facing
proxy for `reporting-service` and `ai-analyst`'s narrative endpoint.

`POST .../reports` never accepts `requested_by` from the browser — it is
always the authenticated `principal.user_id` (Constitution §6). A
`compliance` report additionally requires the `lead` or `tenant_admin`
role (R22) on top of `reports:generate` — a second gate on report
*content*, not a second permission code.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import Field

from sm_common.errors import DependencyUnavailable, NotFound, PermissionDenied
from sm_contracts import Narrative, PermissionCode, Report, ReportDownload, ReportKind, SmBaseModel, ThreatSubjectType

from ..clients import InternalServiceClient
from ..deps import get_internal_client, require_permission
from ..security.principal import Principal
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/soc", tags=["reports"])

_COMPLIANCE_ROLES = frozenset({"lead", "tenant_admin"})

_generate = require_permission(PermissionCode.reports_generate)
_read = require_permission(PermissionCode.reports_read)
# Narrative viewing is the same read tier as viewing detections/timeline —
# no separate permission code invented for it.
_narrative_read = require_permission(PermissionCode.detections_read)


def _require_dict(value: Any, dependency: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DependencyUnavailable(f"{dependency} returned an unexpected response")
    return value


class CreateReportRequest(SmBaseModel):
    kind: ReportKind
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=200)


@router.post("/reports", response_model=Report)
async def create_report(
    body: CreateReportRequest,
    principal: Principal = Depends(_generate),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Report:
    if body.kind == "compliance" and not (principal.roles & _COMPLIANCE_ROLES):
        raise PermissionDenied("compliance reports require the lead or tenant_admin role")
    payload = {
        "kind": body.kind, "subject_type": body.subject_type.value, "subject_id": body.subject_id,
        "title": body.title, "requested_by": str(principal.user_id),
    }
    raw = await client.create_report(principal.tenant_id, payload)
    return Report.model_validate(_require_dict(raw, "reporting-service"))


@router.get("/reports/{report_id}", response_model=ReportDownload)
async def get_report(
    report_id: str,
    principal: Principal = Depends(_read),
    client: InternalServiceClient = Depends(get_internal_client),
) -> ReportDownload:
    raw = await client.get_report(principal.tenant_id, report_id)
    if raw is None:
        raise NotFound("report not found")
    return ReportDownload.model_validate(_require_dict(raw, "reporting-service"))


@router.get("/incidents/{chain_id}/narrative", response_model=Narrative)
async def get_narrative(
    chain_id: str,
    principal: Principal = Depends(_narrative_read),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Narrative:
    raw = await client.get_narrative(principal.tenant_id, chain_id)
    if raw is None:
        raise NotFound("attack chain not found")
    return Narrative.model_validate(_require_dict(raw, "ai-analyst"))
