"""Prometheus exposition endpoint (unauthenticated; network-policy gated)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST

from ..deps import Services, get_services

__all__ = ["router"]

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def metrics(services: Services = Depends(get_services)) -> Response:
    services.metrics.refresh_db_pool(services.db)
    return Response(content=services.metrics.render_latest(), media_type=CONTENT_TYPE_LATEST)
