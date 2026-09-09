from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from sm_common.clock import utcnow
from sm_common.ids import uuid7
from sm_common.security import SensorIdentity
from sm_contracts import EventType, SensorType
from sm_contracts.telemetry import NetworkFlowPayload
from sm_ingestion_gateway.envelope import build_envelope
from sm_ingestion_gateway.kafka_sinks import (
    DLQ_TOPIC,
    RAW_TOPIC,
    KafkaDeadLetterSink,
    KafkaRawEventSink,
)

IDENTITY = SensorIdentity(sensor_id=uuid7(), tenant_id=uuid7(), type=SensorType.network)


class _FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bytes, list[tuple[str, bytes]]]] = []
        self.fail = False

    async def send(
        self, topic: str, *, key: str, value: bytes,
        headers: list[tuple[str, bytes]] | None = None,
    ) -> None:
        if self.fail:
            raise ConnectionError("broker unreachable")
        self.sent.append((topic, key, value, headers or []))


def _envelope() -> Any:
    return build_envelope(
        event_type=EventType.telemetry_network_flow,
        payload_model=NetworkFlowPayload,
        raw_payload={"occurred_at": (utcnow() - timedelta(seconds=1)).isoformat(),
                     "src_ip": "10.0.0.9", "dst_ip": "8.8.8.8", "protocol": "udp"},
        identity=IDENTITY,
    )


async def test_raw_sink_produces_canonical_json_keyed_on_partition_key() -> None:
    producer = _FakeProducer()
    env = _envelope()
    await KafkaRawEventSink(producer).put(env)

    topic, key, value, _ = producer.sent[0]
    assert topic == RAW_TOPIC
    assert key == env.partition_key
    assert json.loads(value)["event_id"] == str(env.event_id)
    assert json.loads(value)["payload"]["protocol"] == "udp"  # subclass field kept


async def test_raw_sink_propagates_producer_failure() -> None:
    producer = _FakeProducer()
    producer.fail = True
    with pytest.raises(ConnectionError):
        await KafkaRawEventSink(producer).put(_envelope())


async def test_dlq_sink_produces_raw_body_with_reason_headers() -> None:
    producer = _FakeProducer()
    sid = uuid4()
    await KafkaDeadLetterSink(producer).put(
        source_type="network_flow", raw_body=b"{bad json", reason="invalid_json", sensor_id=sid
    )
    topic, key, value, headers = producer.sent[0]
    assert topic == DLQ_TOPIC
    assert key == str(sid)
    assert value == b"{bad json"
    assert ("reason", b"invalid_json") in headers
    assert ("source_type", b"network_flow") in headers


async def test_dlq_sink_uses_unknown_key_when_sensor_id_is_none() -> None:
    producer = _FakeProducer()
    await KafkaDeadLetterSink(producer).put(
        source_type="dns_query", raw_body=b"x", reason="invalid_json", sensor_id=None
    )
    _, key, _, headers = producer.sent[0]
    assert key == "unknown"
    assert all(h[0] != "sensor_id" for h in headers)
