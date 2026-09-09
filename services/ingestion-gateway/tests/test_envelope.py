from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from pydantic import ValidationError

from sm_common.clock import utcnow
from sm_common.ids import uuid7
from sm_common.security import SensorIdentity
from sm_contracts import EventType, SensorType, SourceType
from sm_contracts.telemetry import AuthEventPayload, NetworkFlowPayload
from sm_ingestion_gateway.envelope import build_envelope
from sm_ingestion_gateway.version import PRODUCER

NOW = utcnow() - timedelta(seconds=1)
SENSOR_ID = uuid7()
TENANT_ID = uuid7()
IDENTITY = SensorIdentity(sensor_id=SENSOR_ID, tenant_id=TENANT_ID, type=SensorType.network)


def _pkey(primary: str) -> str:
    return hashlib.sha256(f"{TENANT_ID}:{primary}".encode()).hexdigest()[:16]


def test_build_envelope_stamps_server_fields() -> None:
    env = build_envelope(
        event_type=EventType.telemetry_network_flow,
        payload_model=NetworkFlowPayload,
        raw_payload={"occurred_at": NOW.isoformat(), "src_ip": "10.1.2.3",
                     "dst_ip": "8.8.8.8", "protocol": "udp"},
        identity=IDENTITY,
        client_event_id="evt-9",
    )
    assert env.producer == PRODUCER
    assert env.tenant_id == TENANT_ID
    assert env.source.type is SourceType.sensor
    assert env.source.sensor_id == SENSOR_ID
    assert env.occurred_at == NOW
    assert env.event_version == 1
    assert env.partition_key == _pkey("10.1.2.3")
    assert env.metadata == {"sensor_type": "network", "client_event_id": "evt-9"}


def test_partition_key_uses_principal_for_auth_events() -> None:
    env = build_envelope(
        event_type=EventType.telemetry_auth_event,
        payload_model=AuthEventPayload,
        raw_payload={"occurred_at": NOW.isoformat(), "outcome": "success",
                     "auth_type": "ssh", "principal": "alice@corp"},
        identity=IDENTITY,
    )
    assert env.partition_key == _pkey("alice@corp")


def test_future_occurred_at_beyond_skew_is_a_validation_error() -> None:
    future = (NOW + timedelta(minutes=30)).isoformat()
    with pytest.raises(ValidationError):
        build_envelope(
            event_type=EventType.telemetry_network_flow,
            payload_model=NetworkFlowPayload,
            raw_payload={"occurred_at": future, "src_ip": "10.1.2.3",
                         "dst_ip": "8.8.8.8", "protocol": "udp"},
            identity=IDENTITY,
        )


def test_bad_payload_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        build_envelope(
            event_type=EventType.telemetry_network_flow,
            payload_model=NetworkFlowPayload,
            raw_payload={"occurred_at": NOW.isoformat(), "src_ip": "bad",
                         "dst_ip": "8.8.8.8", "protocol": "udp"},
            identity=IDENTITY,
        )
