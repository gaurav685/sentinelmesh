"""`SensorAuth` against a real PostgreSQL.

The unit tests only cover credential parsing and the no-DB rejection paths. The
row lookup, the Argon2 verify, the status / soft-delete gate and the throttled
`last_seen_at` touch are exercised here.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from sm_common.clock import utcnow
from sm_common.db import Database
from sm_common.db.models import Sensor, Tenant
from sm_common.errors import Unauthenticated
from sm_common.ids import uuid7
from sm_common.security import SensorAuth
from sm_common.security.passwords import hash_password
from sm_contracts.enums import SensorStatus, SensorType, TenantStatus

pytestmark = pytest.mark.integration

SECRET = "sensor-secret-correct-horse"


class World:
    def __init__(self) -> None:
        self.tenant = uuid7()
        self.active = uuid7()
        self.disabled = uuid7()
        self.deleted = uuid7()


async def _seed(db: Database) -> World:
    w = World()
    async with db.transaction() as session:
        session.add(
            Tenant(
                id=w.tenant, slug="acme", name="Acme",
                status=TenantStatus.active.value, settings={},
            )
        )
        await session.flush()
        session.add_all(
            [
                Sensor(
                    id=w.active, tenant_id=w.tenant, name="active-sensor",
                    type=SensorType.network.value, status=SensorStatus.active.value,
                    credential_hash=hash_password(SECRET),
                ),
                Sensor(
                    id=w.disabled, tenant_id=w.tenant, name="disabled-sensor",
                    type=SensorType.auth.value, status=SensorStatus.disabled.value,
                    credential_hash=hash_password(SECRET),
                ),
                Sensor(
                    id=w.deleted, tenant_id=w.tenant, name="deleted-sensor",
                    type=SensorType.dns.value, status=SensorStatus.active.value,
                    credential_hash=hash_password(SECRET),
                    deleted_at=utcnow(),
                ),
            ]
        )
    return w


def _cred(sensor_id: UUID, secret: str = SECRET) -> str:
    return f"{sensor_id}.{secret}"


@pytest.mark.asyncio
async def test_active_sensor_authenticates_and_returns_identity(clean: Database):
    w = await _seed(clean)
    auth = SensorAuth()
    async with clean.transaction() as session:
        identity = await auth.authenticate(session, presented_credential=_cred(w.active))
    assert identity.sensor_id == w.active
    assert identity.tenant_id == w.tenant
    assert identity.type is SensorType.network


@pytest.mark.asyncio
async def test_bearer_prefix_is_accepted(clean: Database):
    w = await _seed(clean)
    auth = SensorAuth()
    async with clean.transaction() as session:
        identity = await auth.authenticate(
            session, presented_credential=f"Bearer {_cred(w.active)}"
        )
    assert identity.sensor_id == w.active


@pytest.mark.asyncio
async def test_wrong_secret_is_rejected(clean: Database):
    w = await _seed(clean)
    auth = SensorAuth()
    async with clean.transaction() as session:
        with pytest.raises(Unauthenticated):
            await auth.authenticate(session, presented_credential=_cred(w.active, "wrong"))


@pytest.mark.asyncio
async def test_unknown_sensor_is_rejected(clean: Database):
    await _seed(clean)
    auth = SensorAuth()
    async with clean.transaction() as session:
        with pytest.raises(Unauthenticated):
            await auth.authenticate(session, presented_credential=_cred(uuid7()))


@pytest.mark.asyncio
async def test_disabled_sensor_is_rejected_even_with_the_right_secret(clean: Database):
    w = await _seed(clean)
    auth = SensorAuth()
    async with clean.transaction() as session:
        with pytest.raises(Unauthenticated):
            await auth.authenticate(session, presented_credential=_cred(w.disabled))


@pytest.mark.asyncio
async def test_soft_deleted_sensor_is_rejected(clean: Database):
    w = await _seed(clean)
    auth = SensorAuth()
    async with clean.transaction() as session:
        with pytest.raises(Unauthenticated):
            await auth.authenticate(session, presented_credential=_cred(w.deleted))


@pytest.mark.asyncio
async def test_last_seen_at_is_touched_then_throttled(clean: Database):
    w = await _seed(clean)
    auth = SensorAuth(last_seen_throttle=timedelta(minutes=5))

    async with clean.transaction() as session:
        await auth.authenticate(session, presented_credential=_cred(w.active))
    async with clean.session() as session:
        first = await session.scalar(select(Sensor).where(Sensor.id == w.active))
    assert first is not None and first.last_seen_at is not None
    stamped = first.last_seen_at

    # A second auth inside the throttle window must not write again.
    async with clean.transaction() as session:
        await auth.authenticate(session, presented_credential=_cred(w.active))
    async with clean.session() as session:
        second = await session.scalar(select(Sensor).where(Sensor.id == w.active))
    assert second is not None and second.last_seen_at == stamped
