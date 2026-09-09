"""Typed inference endpoints (ADR-013).

A model that is not registered / not loadable / whose serving deps are missing
→ HTTP 503 `dependency_unavailable` with `MODEL_UNAVAILABLE` in the message and
a `model` detail. `detection-engine` treats that as `scoring_status = DEGRADED`
and falls back to the statistical detector — it is never a 500 and never a
fabricated score.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from sm_common.errors import DependencyUnavailable, ValidationFailed
from sm_common.security import InternalPrincipal
from sm_contracts import ErrorDetail
from sm_ml import FEATURE_SCHEMA_VERSION, schema_for
from sm_ml.models import ModelError, ModelUnavailable

from ..deps import ModelHost, get_host, get_principal
from ..schemas import InferRequest, InferResponse, ModelInfo, ModelsResponse
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=API_PREFIX, tags=["inference"])


def _unavailable(model: str, reason: str) -> DependencyUnavailable:
    return DependencyUnavailable(
        f"MODEL_UNAVAILABLE: {model}",
        details=[ErrorDetail(field="model", issue=reason)],
    )


@router.get("/models", response_model=ModelsResponse)
async def models(
    host: ModelHost = Depends(get_host),
    _principal: InternalPrincipal = Depends(get_principal),
) -> ModelsResponse:
    return ModelsResponse(
        models=[
            ModelInfo(
                name=r.name, version=r.version, method=r.method,
                feature_schema_version=r.feature_schema_version, task=r.task,
            )
            for r in host.catalog()
        ]
    )


@router.post("/infer/{model}", response_model=InferResponse)
async def infer(
    model: str,
    req: InferRequest,
    host: ModelHost = Depends(get_host),
    _principal: InternalPrincipal = Depends(get_principal),
) -> InferResponse:
    if req.feature_schema_version != FEATURE_SCHEMA_VERSION:
        raise ValidationFailed(
            f"feature_schema_version {req.feature_schema_version!r} != "
            f"server {FEATURE_SCHEMA_VERSION!r}"
        )
    expected = len(schema_for(req.kind).names)
    if len(req.features) != expected:
        raise ValidationFailed(
            f"expected {expected} features for kind {req.kind.value}, got {len(req.features)}"
        )

    try:
        estimator = host.get(model)
    except ModelUnavailable as exc:
        host.metrics.request(model, "unavailable")
        raise _unavailable(model, str(exc)) from exc

    start = time.perf_counter()
    try:
        score = estimator.score(req.features)
    except ModelError as exc:
        host.metrics.error(model, type(exc).__name__)
        host.metrics.request(model, "error")
        raise _unavailable(model, f"inference failed: {exc}") from exc
    host.metrics.duration.labels("ml-inference", model).observe(time.perf_counter() - start)
    host.metrics.request(model, "ok")

    return InferResponse(
        model=model,
        method=score.method,
        model_version=score.model_version,
        score=score.score,
        normalized_score=score.normalized_score,
        threshold=score.threshold,
        is_anomaly=score.is_anomaly,
        contributing_features=score.contributing_features,
    )
