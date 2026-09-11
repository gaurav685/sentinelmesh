"""Threat memory + predictive intelligence BFF (Phase 13) — the
browser-facing proxy for `memory-service`.

Every endpoint is behind `require_permission(memory:read)` (deny-by-default,
metered + audited on denial), scopes to `principal.tenant_id` from the
session, and returns a typed `sm_contracts` shape. A prediction is always
returned with its own `confidence` / `evidence` / `model_version` —
`memory-service` never fabricates one, and this proxy never strips those
fields before passing it on.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from sm_common.errors import DependencyUnavailable, NotFound
from sm_contracts import (
    AdversaryFingerprint,
    AttackProgressionRequest,
    Campaign,
    LateralMovementRequest,
    NextActionRequest,
    PermissionCode,
    Prediction,
    SimilarityMatch,
    ThreatMemory,
    ThreatTrajectoryRequest,
)

from ..clients import InternalServiceClient
from ..deps import get_internal_client, require_permission
from ..security.principal import Principal
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/soc", tags=["memory"])

_memory = require_permission(PermissionCode.memory_read)


def _require_dict(value: Any, dependency: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DependencyUnavailable(f"{dependency} returned an unexpected response")
    return value


# ---- threat memory retrieval ------------------------------------
@router.post("/memory/similar", response_model=list[SimilarityMatch])
async def find_similar(
    # `memory-service` owns and validates the request shape (kind,
    # technique_ids, limit); a malformed body comes back as its own 422,
    # surfaced here as `ValidationFailed` by `InternalServiceClient._request`.
    body: dict[str, Any],
    principal: Principal = Depends(_memory),
    client: InternalServiceClient = Depends(get_internal_client),
) -> list[SimilarityMatch]:
    raw = await client.mem_similar(principal.tenant_id, body)
    if not isinstance(raw, list):
        raise DependencyUnavailable("memory-service returned an unexpected response")
    return [SimilarityMatch.model_validate(row) for row in raw]


@router.get("/memory/patterns", response_model=list[ThreatMemory])
async def list_patterns(
    subject_type: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    principal: Principal = Depends(_memory),
    client: InternalServiceClient = Depends(get_internal_client),
) -> list[ThreatMemory]:
    raw = await client.mem_patterns(principal.tenant_id, subject_type=subject_type, subject_id=subject_id)
    if not isinstance(raw, list):
        raise DependencyUnavailable("memory-service returned an unexpected response")
    return [ThreatMemory.model_validate(row) for row in raw]


@router.get("/memory/fingerprints/{subject_type}/{subject_id}", response_model=AdversaryFingerprint)
async def get_fingerprint(
    subject_type: str,
    subject_id: str,
    principal: Principal = Depends(_memory),
    client: InternalServiceClient = Depends(get_internal_client),
) -> AdversaryFingerprint:
    raw = await client.mem_fingerprint(principal.tenant_id, subject_type, subject_id)
    if raw is None:
        raise NotFound("no fingerprint for that subject")
    return AdversaryFingerprint.model_validate(_require_dict(raw, "memory-service"))


@router.get("/memory/campaigns", response_model=list[Campaign])
async def list_campaigns(
    status: str | None = Query(default=None),
    principal: Principal = Depends(_memory),
    client: InternalServiceClient = Depends(get_internal_client),
) -> list[Campaign]:
    raw = await client.mem_campaigns(principal.tenant_id, status=status)
    if not isinstance(raw, list):
        raise DependencyUnavailable("memory-service returned an unexpected response")
    return [Campaign.model_validate(row) for row in raw]


@router.get("/memory/campaigns/{campaign_id}", response_model=Campaign)
async def get_campaign(
    campaign_id: str,
    principal: Principal = Depends(_memory),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Campaign:
    raw = await client.mem_campaign(principal.tenant_id, campaign_id)
    if raw is None:
        raise NotFound("campaign not found")
    return Campaign.model_validate(_require_dict(raw, "memory-service"))


# ---- predictive intelligence --------------------------------------
@router.post("/predict/attack-progression", response_model=Prediction)
async def predict_attack_progression(
    body: AttackProgressionRequest,
    principal: Principal = Depends(_memory),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Prediction:
    raw = await client.predict_attack_progression(principal.tenant_id, body.model_dump(mode="json"))
    return Prediction.model_validate(_require_dict(raw, "memory-service"))


@router.post("/predict/next-action", response_model=Prediction)
async def predict_next_action(
    body: NextActionRequest,
    principal: Principal = Depends(_memory),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Prediction:
    raw = await client.predict_next_action(principal.tenant_id, body.model_dump(mode="json"))
    return Prediction.model_validate(_require_dict(raw, "memory-service"))


@router.post("/predict/lateral-movement", response_model=Prediction)
async def predict_lateral_movement(
    body: LateralMovementRequest,
    principal: Principal = Depends(_memory),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Prediction:
    raw = await client.predict_lateral_movement(principal.tenant_id, body.model_dump(mode="json"))
    return Prediction.model_validate(_require_dict(raw, "memory-service"))


@router.post("/predict/threat-trajectory", response_model=Prediction)
async def predict_threat_trajectory(
    body: ThreatTrajectoryRequest,
    principal: Principal = Depends(_memory),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Prediction:
    raw = await client.predict_threat_trajectory(principal.tenant_id, body.model_dump(mode="json"))
    return Prediction.model_validate(_require_dict(raw, "memory-service"))
