"""Sensor credential authentication (Engineering Constitution §5, §6; R1).

A sensor authenticates to the ingestion gateway with a single opaque credential
of the shape ``<sensor_id>.<secret>`` (an optional ``Bearer `` prefix is
tolerated so it can be carried in a standard ``Authorization`` header). The
``sensor_id`` is the row's UUID; the secret is shown once at registration and
stored only as an Argon2id hash in ``sensor.credential_hash``.

Properties:

- **No enumeration, no timing oracle.** An unknown ``sensor_id`` still pays the
  Argon2 verification cost via ``dummy_verify``. The secret is verified before
  the status / soft-delete checks so a disabled sensor and an active one with a
  bad secret are indistinguishable by timing.
- **One generic failure.** Every rejection — malformed credential, unknown
  sensor, wrong secret, ``status != active``, ``deleted_at`` set — raises the
  same :class:`~sm_common.errors.Unauthenticated`. The reason is never told to
  the caller; the gateway meters it.
- **Liveness tracking.** ``last_seen_at`` is touched on success, throttled to at
  most one write per ``last_seen_throttle`` so a chatty sensor does not turn its
  registry row into a write hot-spot. ``authenticate`` must therefore run inside
  a transaction (``Database.transaction()``); the touch commits with the
  caller's unit of work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_contracts import SensorStatus, SensorType

from ..clock import utcnow
from ..db.models import Sensor
from ..errors import Unauthenticated
from .passwords import dummy_verify, verify_password

__all__ = ["SensorAuth", "SensorIdentity"]

_BEARER_PREFIX = "Bearer "
_DEFAULT_LAST_SEEN_THROTTLE = timedelta(seconds=60)


@dataclass(frozen=True)
class SensorIdentity:
    """The authenticated sensor. Everything the gateway needs to stamp an
    envelope — the ``tenant_id`` in particular is taken from here and never from
    the request body."""

    sensor_id: UUID
    tenant_id: UUID
    type: SensorType


def _parse_credential(presented: str) -> tuple[str, str] | None:
    """Split ``<sensor_id>.<secret>`` (with an optional ``Bearer `` prefix).

    Returns ``(sensor_id, secret)`` or ``None`` when the shape is wrong.
    """
    token = presented.strip()
    if token.startswith(_BEARER_PREFIX):
        token = token[len(_BEARER_PREFIX) :].strip()
    sensor_id, sep, secret = token.partition(".")
    if not sep or not sensor_id or not secret:
        return None
    return sensor_id, secret


class SensorAuth:
    def __init__(self, *, last_seen_throttle: timedelta = _DEFAULT_LAST_SEEN_THROTTLE) -> None:
        self._throttle = last_seen_throttle

    async def authenticate(
        self, session: AsyncSession, *, presented_credential: str
    ) -> SensorIdentity:
        parsed = _parse_credential(presented_credential)
        if parsed is None:
            # Burn comparable work even when there is nothing to look up.
            dummy_verify(presented_credential or "")
            raise Unauthenticated()

        raw_id, secret = parsed
        try:
            sensor_id = UUID(raw_id)
        except ValueError:
            dummy_verify(secret)
            raise Unauthenticated() from None

        sensor = await session.scalar(select(Sensor).where(Sensor.id == sensor_id))
        if sensor is None:
            dummy_verify(secret)
            raise Unauthenticated()

        # Verify before the status / soft-delete checks: the time spent must not
        # depend on whether the sensor is active.
        secret_ok = verify_password(sensor.credential_hash, secret).ok
        if not secret_ok or sensor.deleted_at is not None or sensor.status != SensorStatus.active.value:
            raise Unauthenticated()

        now = utcnow()
        if sensor.last_seen_at is None or now - sensor.last_seen_at >= self._throttle:
            await session.execute(
                update(Sensor).where(Sensor.id == sensor_id).values(last_seen_at=now)
            )

        return SensorIdentity(
            sensor_id=sensor_id, tenant_id=sensor.tenant_id, type=SensorType(sensor.type)
        )
