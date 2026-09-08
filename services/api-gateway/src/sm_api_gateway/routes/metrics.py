"""Prometheus exposition endpoint.

Deliberately **not** under `/api/v1` and deliberately unauthenticated: Prometheus
scrapes it from inside the cluster network. The ingress must never route to
`/metrics` (see `docs/architecture/deployment.md`); exposure is controlled by
network policy, not by application auth, because a scrape has no session.

The body contains only counters and histograms this process produced. No metric
value is ever synthesized.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST

from ..deps import Services, get_services

__all__ = ["router"]

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def metrics(services: Services = Depends(get_services)) -> Response:
    return Response(content=services.metrics.render_latest(), media_type=CONTENT_TYPE_LATEST)
