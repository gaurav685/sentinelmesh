"""The ingest endpoints.

- `POST /api/v1/ingest/{source_type}` — one bare telemetry payload. The envelope
  is built server-side. `202` on accept, `200` when suppressed as a duplicate
  `X-Sensor-Event-Id`, `404` for an unknown `source_type`, `422` (+ DLQ) for bad
  JSON or a failed payload schema.
- `POST /api/v1/ingest/batch` — `{source_type, events: [...]}`, up to
  `SM_INGEST_BATCH_MAX_EVENTS`. Always `202`; per-element failures come back in
  `rejected` and are dead-lettered.

Both require sensor authentication (`Authorization: <sensor_id>.<secret>`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response, status

from sm_common.errors import ValidationFailed
from sm_common.security import SensorIdentity

from ..deps import Services, get_ingest_context, get_sensor, get_services
from ..pipeline import IngestContext, IngestOutcome, ingest_batch, ingest_one
from ..schemas import BatchIngestRequest, BatchIngestResult, IngestAccepted, RejectedItem
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/ingest", tags=["ingest"])


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED, response_model=BatchIngestResult)
async def ingest_batch_endpoint(
    body: BatchIngestRequest,
    identity: SensorIdentity = Depends(get_sensor),
    ctx: IngestContext = Depends(get_ingest_context),
    services: Services = Depends(get_services),
) -> BatchIngestResult:
    limit = services.settings.ingest_batch_max_events
    if len(body.events) > limit:
        raise ValidationFailed(f"batch has {len(body.events)} events; the limit is {limit}")

    result = await ingest_batch(
        ctx, identity=identity, source_type=body.source_type, events=body.events
    )
    return BatchIngestResult(
        accepted=len(result.event_ids),
        rejected=[RejectedItem(index=i, reason=r) for i, r in result.rejected],
        event_ids=result.event_ids,
    )


@router.post("/{source_type}", status_code=status.HTTP_202_ACCEPTED, response_model=IngestAccepted)
async def ingest_one_endpoint(
    source_type: str,
    request: Request,
    response: Response,
    identity: SensorIdentity = Depends(get_sensor),
    ctx: IngestContext = Depends(get_ingest_context),
    x_sensor_event_id: str | None = Header(default=None),
) -> IngestAccepted:
    raw_body = await request.body()
    result = await ingest_one(
        ctx,
        identity=identity,
        source_type=source_type,
        raw_body=raw_body,
        client_event_id=x_sensor_event_id,
    )
    if result.outcome is IngestOutcome.duplicate:
        response.status_code = status.HTTP_200_OK
        return IngestAccepted(event_id=None, deduplicated=True)
    return IngestAccepted(event_id=result.event_id)
