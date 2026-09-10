"""SOC read API (Phase 9) — the browser-facing BFF.

Every endpoint:
- is behind `require_permission` (deny-by-default, metered + audited on denial);
- scopes to `principal.tenant_id` from the session — never a query field;
- returns a typed `sm_contracts` shape (the frontend's generated client consumes
  these; it never re-declares them);
- surfaces a dependency failure as HTTP 503 (`DependencyUnavailable`), never a
  raw 500 and never a fabricated result.

Detections / alerts / threat-scores / the MITRE heatmap / an entity timeline are
read straight from Postgres (they have no internal read API). Attack chains, the
graph and threat intel are proxied to their owning service with a minted service
token scoped to the caller's tenant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sm_common.errors import DependencyUnavailable, NotFound
from sm_contracts import (
    CursorPage,
    Detection,
    GraphNeighborhood,
    GraphPath,
    MitreHeatmap,
    PermissionCode,
    SecurityAlert,
    ThreatScore,
    TimelineResponse,
)
from sm_contracts import SocSummary as SocSummaryModel

from ..clients import InternalServiceClient
from ..deps import get_internal_client, get_soc_repository, require_permission
from ..repositories.protocols import SocRepository
from ..security.principal import Principal
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/soc", tags=["soc"])

_read = require_permission(PermissionCode.detections_read)
_hunt = require_permission(PermissionCode.hunt_query)


def _page(items: list[Any], limit: int, cursor_attr: str) -> CursorPage[Any]:
    nxt: str | None = None
    if len(items) == limit and items:
        nxt = getattr(items[-1], cursor_attr).isoformat()
    return CursorPage[Any](items=items, next_cursor=nxt, limit=limit)


# ---- dashboard ---------------------------------------------------
@router.get("/summary", response_model=SocSummaryModel)
async def summary(
    principal: Principal = Depends(_read),
    repo: SocRepository = Depends(get_soc_repository),
) -> SocSummaryModel:
    return await repo.summary(principal.tenant_id)


# ---- detections -----------------------------------------------
@router.get("/detections", response_model=CursorPage[Detection])
async def detections(
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = Query(default=None),
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    principal: Principal = Depends(_read),
    repo: SocRepository = Depends(get_soc_repository),
) -> CursorPage[Detection]:
    items = await repo.list_detections(
        principal.tenant_id, limit=limit, before=before, severity=severity, status=status
    )
    return _page(items, limit, "created_at")


@router.get("/detections/{detection_id}", response_model=Detection)
async def detection(
    detection_id: UUID,
    principal: Principal = Depends(_read),
    repo: SocRepository = Depends(get_soc_repository),
) -> Detection:
    found = await repo.get_detection(principal.tenant_id, detection_id)
    if found is None:
        raise NotFound("detection not found")
    return found


# ---- alerts / incidents --------------------------------------
@router.get("/alerts", response_model=CursorPage[SecurityAlert])
async def alerts(
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = Query(default=None),
    status: str | None = Query(default=None),
    principal: Principal = Depends(_read),
    repo: SocRepository = Depends(get_soc_repository),
) -> CursorPage[SecurityAlert]:
    items = await repo.list_alerts(principal.tenant_id, limit=limit, before=before, status=status)
    return _page(items, limit, "created_at")


@router.get("/alerts/{alert_id}", response_model=SecurityAlert)
async def alert(
    alert_id: UUID,
    principal: Principal = Depends(_read),
    repo: SocRepository = Depends(get_soc_repository),
) -> SecurityAlert:
    found = await repo.get_alert(principal.tenant_id, alert_id)
    if found is None:
        raise NotFound("alert not found")
    return found


# ---- risk / threat scores -----------------------------------
@router.get("/risk", response_model=list[ThreatScore])
async def risk(
    limit: int = Query(default=25, ge=1, le=200),
    principal: Principal = Depends(_read),
    repo: SocRepository = Depends(get_soc_repository),
) -> list[ThreatScore]:
    return await repo.top_risk(principal.tenant_id, limit=limit)


# ---- MITRE heatmap -----------------------------------------
@router.get("/mitre/heatmap", response_model=MitreHeatmap)
async def mitre_heatmap(
    principal: Principal = Depends(_read),
    repo: SocRepository = Depends(get_soc_repository),
    client: InternalServiceClient = Depends(get_internal_client),
) -> MitreHeatmap:
    cells = await repo.mitre_heatmap(principal.tenant_id)
    matrix_version: str | None = None
    try:
        remote = await client.mitre_heatmap(principal.tenant_id)
        if isinstance(remote, dict):
            matrix_version = remote.get("matrix_version")
    except Exception:
        matrix_version = None
    return MitreHeatmap(matrix_version=matrix_version, cells=cells)


# ---- entity timeline --------------------------------------
@router.get("/timeline/{subject_id}", response_model=TimelineResponse)
async def timeline(
    subject_id: str,
    subject_type: str = Query(default="host"),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(_read),
    repo: SocRepository = Depends(get_soc_repository),
) -> TimelineResponse:
    from sm_contracts import ThreatSubjectType

    entries = await repo.entity_timeline(principal.tenant_id, subject_id, limit=limit)
    return TimelineResponse(
        subject_type=ThreatSubjectType(subject_type), subject_id=subject_id, entries=entries
    )


# ---- attack chains (proxy: correlation-engine) --------------
@router.get("/chains")
async def chains(
    status: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(_read),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Any:
    return await client.chains(
        principal.tenant_id, status=status, min_score=min_score, limit=limit
    )


@router.get("/chains/{chain_id}")
async def chain(
    chain_id: UUID,
    principal: Principal = Depends(_read),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Any:
    found = await client.chain(principal.tenant_id, str(chain_id))
    if found is None:
        raise NotFound("attack chain not found")
    return found


# ---- graph (proxy: graph-service) -------------------------
@router.get("/graph/neighbors", response_model=GraphNeighborhood)
async def graph_neighbors(
    label: str = Query(...),
    key: str = Query(...),
    depth: int = Query(default=1, ge=1, le=6),
    principal: Principal = Depends(_hunt),
    client: InternalServiceClient = Depends(get_internal_client),
) -> GraphNeighborhood:
    raw = await client.graph_neighbors(principal.tenant_id, label=label, key=key, depth=depth)
    if not isinstance(raw, dict):
        raise DependencyUnavailable("graph-service returned an unexpected response")
    return GraphNeighborhood(
        root_id=raw.get("root_id") or key,
        depth=raw.get("depth", depth),
        nodes=raw.get("nodes", []),
        edges=raw.get("edges", []),
        truncated=bool(raw.get("truncated", False)),
    )


@router.get("/graph/paths", response_model=GraphPath)
async def graph_paths(
    src_label: str = Query(...),
    src_key: str = Query(...),
    dst_label: str = Query(...),
    dst_key: str = Query(...),
    max_depth: int = Query(default=4, ge=1, le=8),
    principal: Principal = Depends(_hunt),
    client: InternalServiceClient = Depends(get_internal_client),
) -> GraphPath:
    raw = await client.graph_paths(
        principal.tenant_id, src_label=src_label, src_key=src_key,
        dst_label=dst_label, dst_key=dst_key, max_depth=max_depth,
    )
    if not isinstance(raw, dict):
        raise DependencyUnavailable("graph-service returned an unexpected response")
    return GraphPath(
        found=bool(raw.get("found", False)),
        length=raw.get("length"),
        nodes=raw.get("nodes", []),
        edges=raw.get("edges", []),
    )


@router.get("/graph/intel")
async def graph_intel(
    label: str = Query(...),
    key: str = Query(...),
    depth: int = Query(default=2, ge=1, le=4),
    principal: Principal = Depends(_hunt),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Any:
    found = await client.graph_intel(principal.tenant_id, label=label, key=key, depth=depth)
    if found is None:
        raise NotFound("entity not found")
    return found


# ---- threat intel (proxy: threat-intel-service) -----------
@router.get("/ti/indicators")
async def ti_indicators(
    type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    principal: Principal = Depends(_read),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Any:
    return await client.ti_indicators(principal.tenant_id, type=type, limit=limit)
