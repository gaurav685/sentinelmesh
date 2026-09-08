from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sm_contracts import (
    EventEnvelope,
    EventSource,
    EventType,
    SourceType,
    UserEventAction,
    UserEventPayload,
)

UserEventEnvelope = EventEnvelope[UserEventPayload]


def _base_kwargs(**overrides):
    now = datetime.now(UTC)
    kwargs = dict(
        event_id=uuid4(),
        event_type=EventType.user_event,
        event_version=1,
        occurred_at=now,
        ingested_at=now,
        producer="api-gateway@0.1.0",
        tenant_id=uuid4(),
        source=EventSource(type=SourceType.internal),
        correlation_id=uuid4(),
        partition_key="t:abc123",
        payload=UserEventPayload(action=UserEventAction.created, user_id=uuid4()),
        metadata={},
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_envelope_roundtrips():
    env = UserEventEnvelope(**_base_kwargs())
    dumped = env.model_dump_json()
    reparsed = UserEventEnvelope.model_validate_json(dumped)
    assert reparsed == env


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        UserEventEnvelope(**_base_kwargs(occurred_at=datetime(2026, 1, 1, 0, 0, 0)))  # noqa: DTZ001  (intentionally naive)


def test_datetime_normalized_to_utc():
    tz = timezone(timedelta(hours=5, minutes=30))
    env = UserEventEnvelope(**_base_kwargs(occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz)))
    assert env.occurred_at.tzinfo == UTC
    assert env.occurred_at.hour == 6 and env.occurred_at.minute == 30


def test_future_occurred_at_beyond_skew_rejected():
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        UserEventEnvelope(**_base_kwargs(occurred_at=now + timedelta(minutes=10), ingested_at=now))


def test_bad_producer_rejected():
    for bad in ("api-gateway", "APIGW@1.0.0", "svc@1.0", "svc@v1.0.0"):
        with pytest.raises(ValidationError):
            UserEventEnvelope(**_base_kwargs(producer=bad))


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        UserEventEnvelope(**_base_kwargs(surprise="x"))


def test_sensor_id_only_valid_for_sensor_source():
    with pytest.raises(ValidationError):
        EventSource(type=SourceType.internal, sensor_id=uuid4())
    ok = EventSource(type=SourceType.sensor, sensor_id=uuid4())
    assert ok.sensor_id is not None


def test_role_action_requires_role_id():
    with pytest.raises(ValidationError):
        UserEventPayload(action=UserEventAction.role_granted, user_id=uuid4())
    ok = UserEventPayload(action=UserEventAction.role_granted, user_id=uuid4(), role_id=uuid4())
    assert ok.role_id is not None


def test_event_version_must_be_positive():
    with pytest.raises(ValidationError):
        UserEventEnvelope(**_base_kwargs(event_version=0))
