"""Real-dataset ingestion BFF (Phase 18 follow-up).

Lets an authenticated, permission-checked analyst upload a real, public
dataset file and replay it through the real ingestion pipeline -- a
different trust boundary than `simulation-service`'s synthetic scenarios
(Phase 12, session-authenticated but produces `simulated: true` data) and
than a real sensor's own credential (Phase 2, a device secret, not a human
session). Only NSL-KDD's real network-connection format is understood; an
unrecognized format is refused with a real 422, never guessed at.

`ingestion-gateway` only accepts sensor-credential auth
(`Authorization: <sensor_id>.<secret>`), not the internal-JWT scheme every
other `InternalServiceClient` call uses -- so this route talks to it
directly over `services.http`, not through that client. A per-tenant
"web-upload" sensor row is created once and given a **fresh** credential on
every upload (the old one is never retrievable -- `credential_hash` is
one-way -- and nothing else needs this sensor's identity to be stable
across requests).
"""

from __future__ import annotations

import secrets
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select

from sm_common.db.models import Sensor
from sm_common.errors import DependencyUnavailable, ValidationFailed
from sm_common.security.passwords import hash_password
from sm_contracts import DatasetUploadResult, PermissionCode

from ..deps import Services, get_services, require_permission
from ..nsl_kdd import NslKddParseError, parse_nsl_kdd
from ..security.principal import Principal
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/soc/datasets", tags=["datasets"])

_import_perm = require_permission(PermissionCode.sensors_manage)
_SENSOR_NAME = "web-upload"
_BATCH_SIZE = 100


async def _get_or_create_sensor(services: Services, tenant_id: UUID) -> tuple[str, str]:
    """Return `(sensor_id, secret)` for the tenant's web-upload sensor,
    minting a fresh secret every call."""
    secret = secrets.token_urlsafe(32)
    async with services.db.transaction() as session:
        sensor = await session.scalar(
            select(Sensor).where(Sensor.tenant_id == tenant_id, Sensor.name == _SENSOR_NAME)
        )
        if sensor is None:
            sensor = Sensor(
                tenant_id=tenant_id, name=_SENSOR_NAME, type="network",
                status="active", credential_hash=hash_password(secret),
            )
            session.add(sensor)
            await session.flush()
        else:
            sensor.credential_hash = hash_password(secret)
            sensor.status = "active"
        sensor_id = str(sensor.id)
    return sensor_id, secret


@router.post("/nsl-kdd", response_model=DatasetUploadResult)
async def upload_nsl_kdd(
    file: UploadFile = File(...),
    principal: Principal = Depends(_import_perm),
    services: Services = Depends(get_services),
) -> DatasetUploadResult:
    raw = await file.read()
    try:
        parsed = parse_nsl_kdd(raw)
    except NslKddParseError as exc:
        raise ValidationFailed(str(exc)) from exc

    sensor_id, secret = await _get_or_create_sensor(services, principal.tenant_id)
    credential = f"{sensor_id}.{secret}"

    if services.http is None:
        raise DependencyUnavailable("no HTTP client configured for ingestion-gateway")
    base_url = services.settings.ingestion_gateway_url.rstrip("/")

    accepted = 0
    rejected = 0
    for start in range(0, len(parsed.events), _BATCH_SIZE):
        chunk = parsed.events[start : start + _BATCH_SIZE]
        try:
            resp = await services.http.post(
                f"{base_url}{API_PREFIX}/ingest/batch",
                json={"source_type": "network_flow", "events": chunk},
                headers={"Authorization": credential},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise DependencyUnavailable(f"ingestion-gateway unreachable: {exc}") from exc
        body = resp.json()
        accepted += int(body.get("accepted", 0))
        rejected += len(body.get("rejected", []))

    return DatasetUploadResult(
        dataset="nsl-kdd",
        rows_read=parsed.rows_read,
        accepted=accepted,
        rejected=rejected,
        ground_truth_labels=parsed.ground_truth_labels,
        sensor_id=sensor_id,
    )
