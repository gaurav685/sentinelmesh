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
    EvidenceRef,
    ExplainRequest,
    Explanation,
    GraphNeighborhood,
    GraphPath,
    HuntResult,
    MitreHeatmap,
    PermissionCode,
    SecurityAlert,
    SocHuntRequest,
    SocHuntResponse,
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


@router.get("/detections/{detection_id}/explanation", response_model=Explanation)
async def detection_explanation(
    detection_id: UUID,
    task: str = Query(default="summarize"),
    principal: Principal = Depends(_read),
    repo: SocRepository = Depends(get_soc_repository),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Explanation:
    """Gather the evidence for a detection (tenant-scoped, read-only) and ask
    `ai-analyst` to explain it. The analyst answers only from this evidence."""
    found = await repo.get_detection(principal.tenant_id, detection_id)
    if found is None:
        raise NotFound("detection not found")
    request = _explain_request_for_detection(found, task)
    raw = await client.explain(principal.tenant_id, request.model_dump(mode="json"))
    if not isinstance(raw, dict):
        raise DependencyUnavailable("ai-analyst returned an unexpected response")
    return Explanation.model_validate(raw)


def _explain_request_for_detection(det: Detection, task: str) -> ExplainRequest:
    did = str(det.id)
    evidence: list[EvidenceRef] = [
        EvidenceRef(
            kind="detection",
            ref=did,
            provenance=f"detection-engine:{did}",
            content=f"{det.title}. {det.description}".strip(),
        ),
        EvidenceRef(
            kind="detection_meta",
            ref=f"{did}:meta",
            provenance=f"detection-engine:{did}",
            content=(
                f"detector={det.detector} rule_id={det.rule_id or 'n/a'} "
                f"severity={det.severity} score={det.score:.2f} status={det.status} "
                f"first_seen={det.first_seen.isoformat()} last_seen={det.last_seen.isoformat()}"
            ),
            trusted=True,
        ),
    ]
    for i, ent in enumerate(det.entities[:20]):
        evidence.append(
            EvidenceRef(
                kind="entity",
                ref=f"{did}:e{i}",
                provenance=f"detection-engine:{did}",
                content=f"{ent.kind.value}={ent.value}",
            )
        )
    for tech in det.technique_ids[:20]:
        evidence.append(
            EvidenceRef(
                kind="technique",
                ref=tech,
                provenance="detection-engine:rule",
                content=f"ATT&CK technique {tech} (named by the detection rule)",
                trusted=True,
            )
        )
    allowed = {"summarize", "triage", "reason", "remediate"}
    safe_task = task if task in allowed else "summarize"
    return ExplainRequest.model_validate(
        {
            "subject_type": "detection",
            "subject_id": did,
            "task": safe_task,
            "evidence": [e.model_dump() for e in evidence],
        }
    )


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


# ---- threat hunting (Phase 11) -----------------------------
@router.post("/hunt", response_model=SocHuntResponse)
async def hunt(
    body: SocHuntRequest,
    principal: Principal = Depends(_hunt),
    repo: SocRepository = Depends(get_soc_repository),
    client: InternalServiceClient = Depends(get_internal_client),
) -> SocHuntResponse:
    """Run a threat hunt. `body.plan` = a structured plan built by the UI (no
    LLM); `body.query` = natural language, translated to a `QueryPlan` by
    `ai-analyst`. Either way the plan is executed by `graph-service` scoped to
    `principal.tenant_id` (never a body field). The natural-language text is
    never sent to `graph-service` and never becomes a query."""
    tenant = principal.tenant_id

    plan_dict: dict[str, Any]
    mode: str
    nl_query: str | None
    if body.plan is not None:
        plan_dict = body.plan.model_dump(mode="json")
        mode, nl_query = "quick", None
    elif body.query is not None:
        mode, nl_query = "nl", body.query
        planned = await client.hunt_plan(
            tenant, {"query": body.query, "max_rows": body.max_rows}
        )
        if not isinstance(planned, dict):
            raise DependencyUnavailable("ai-analyst returned an unexpected response")
        if not planned.get("supported") or not planned.get("plan"):
            await repo.record_hunt(
                tenant, principal=principal.email, mode=mode, nl_query=nl_query,
                intent=None, supported=False, row_count=0, cypher_fingerprint=None,
            )
            return SocHuntResponse(
                supported=False,
                unsupported_reason=str(planned.get("unsupported_reason", "could not plan the query")),
            )
        plan_dict = planned["plan"]
    else:
        return SocHuntResponse(supported=False, unsupported_reason="provide 'query' or 'plan'")

    raw = await client.graph_hunt(tenant, plan_dict)
    if not isinstance(raw, dict):
        raise DependencyUnavailable("graph-service returned an unexpected response")
    result = HuntResult.model_validate(raw)

    # best-effort grounded explanation; a failure here does not fail the hunt
    try:
        explained = await client.hunt_explain(
            tenant, {"result": result.model_dump(mode="json")}
        )
        if isinstance(explained, dict):
            result = HuntResult.model_validate(explained)
    except DependencyUnavailable:
        pass

    history_id = await repo.record_hunt(
        tenant, principal=principal.email, mode=mode, nl_query=nl_query,
        intent=result.intent, supported=True, row_count=result.row_count,
        cypher_fingerprint=result.cypher_fingerprint or None,
    )
    return SocHuntResponse(supported=True, result=result, history_id=str(history_id))
