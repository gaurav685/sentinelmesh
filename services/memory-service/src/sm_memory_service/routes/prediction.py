"""Predictive-intelligence API. Internal-JWT only.

Every response is a `Prediction` carrying its own confidence, evidence, and
model version — see `sm_ml.predict` for why nothing here is a trained model.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_common.security import InternalPrincipal
from sm_contracts import (
    AttackProgressionRequest,
    LateralMovementRequest,
    NextActionRequest,
    Prediction,
    ThreatTrajectoryRequest,
)

from ..deps import Services, get_principal, get_services
from ..predictions import PredictionService
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/predict", tags=["predict"])


def _service(services: Services) -> PredictionService:
    return PredictionService(repo=services.repo, chains=services.chains)


@router.post("/attack-progression", response_model=Prediction)
async def attack_progression(
    body: AttackProgressionRequest,
    principal: InternalPrincipal = Depends(get_principal),
    services: Services = Depends(get_services),
) -> Prediction:
    return await _service(services).attack_progression(principal.tenant_id, body.chain_id)


@router.post("/next-action", response_model=Prediction)
async def next_action(
    body: NextActionRequest,
    principal: InternalPrincipal = Depends(get_principal),
    services: Services = Depends(get_services),
) -> Prediction:
    return await _service(services).next_action(principal.tenant_id, body.chain_id)


@router.post("/lateral-movement", response_model=Prediction)
async def lateral_movement(
    body: LateralMovementRequest,
    principal: InternalPrincipal = Depends(get_principal),
    services: Services = Depends(get_services),
) -> Prediction:
    return await _service(services).lateral_movement(
        principal.tenant_id, subject_type=body.subject_type, subject_id=body.subject_id
    )


@router.post("/threat-trajectory", response_model=Prediction)
async def threat_trajectory(
    body: ThreatTrajectoryRequest,
    principal: InternalPrincipal = Depends(get_principal),
    services: Services = Depends(get_services),
) -> Prediction:
    return await _service(services).threat_trajectory(principal.tenant_id, body.campaign_id)
