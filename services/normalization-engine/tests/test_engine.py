from __future__ import annotations

import json
from typing import Any

import pytest

from sm_normalization_engine.topics import CANONICAL_TOPIC, DLQ_TOPIC


async def test_good_record_produces_a_canonical_envelope(
    rig: Any, make_envelope_fn: Any, make_record_fn: Any
) -> None:
    env = make_envelope_fn("network_flow", src_ip="10.0.0.1", dst_ip="8.8.8.8", protocol="tcp")
    await rig.engine.handle(make_record_fn(env.model_dump_json().encode()))

    out = rig.producer.to(CANONICAL_TOPIC)
    assert len(out) == 1
    doc = out[0]
    assert doc["event_type"] == "event.canonical"
    assert doc["producer"].startswith("normalization-engine@")
    assert doc["tenant_id"] == str(env.tenant_id)
    assert doc["correlation_id"] == str(env.correlation_id)
    assert doc["metadata"]["raw_event_id"] == str(env.event_id)
    assert doc["payload"]["raw_event_id"] == str(env.event_id)
    assert doc["payload"]["kind"] == "network_flow"
    assert not rig.producer.to(DLQ_TOPIC)


async def test_unparseable_record_is_dead_lettered(rig: Any, make_record_fn: Any) -> None:
    await rig.engine.handle(make_record_fn(b"{ not json"))
    dlq = rig.producer.to(DLQ_TOPIC)
    assert len(dlq) == 1
    assert dlq[0]["error_type"] == "unparseable"
    assert dlq[0]["consumer_group"] == "normalization"
    assert dlq[0]["original"] == "{ not json"
    assert not rig.producer.to(CANONICAL_TOPIC)


async def test_unknown_event_type_is_dead_lettered(rig: Any, make_record_fn: Any) -> None:
    await rig.engine.handle(
        make_record_fn(json.dumps({"event_type": "user.event", "x": 1}).encode())
    )
    dlq = rig.producer.to(DLQ_TOPIC)
    assert len(dlq) == 1
    assert dlq[0]["error_type"] in {"unknown_event_type", "envelope_invalid"}


async def test_invalid_envelope_is_dead_lettered(
    rig: Any, make_envelope_fn: Any, make_record_fn: Any
) -> None:
    env = make_envelope_fn("network_flow", src_ip="10.0.0.1", dst_ip="8.8.8.8", protocol="tcp")
    doc = json.loads(env.model_dump_json())
    doc.pop("correlation_id")
    await rig.engine.handle(make_record_fn(json.dumps(doc).encode()))
    dlq = rig.producer.to(DLQ_TOPIC)
    assert len(dlq) == 1
    assert dlq[0]["error_type"] == "envelope_invalid"


async def test_produce_failure_raises_after_retries(
    rig: Any, make_envelope_fn: Any, make_record_fn: Any
) -> None:
    rig.producer.fail = True
    env = make_envelope_fn("dns_query", client_ip="10.0.0.5", query_name="x.com", query_type="A")
    with pytest.raises(RuntimeError):
        await rig.engine.handle(make_record_fn(env.model_dump_json().encode()))


async def test_dlq_key_falls_back_to_unknown_without_a_record_key(
    rig: Any, make_record_fn: Any
) -> None:
    await rig.engine.handle(make_record_fn(b"nope", key=None))
    topic, key, _ = rig.producer.sent[0]
    assert topic == DLQ_TOPIC
    assert key == "unknown"


async def test_each_source_type_round_trips_through_handle(
    rig: Any, make_envelope_fn: Any, make_record_fn: Any
) -> None:
    cases: list[tuple[str, dict[str, Any]]] = [
        ("network_flow", {"src_ip": "1.1.1.1", "dst_ip": "8.8.8.8", "protocol": "udp"}),
        ("auth_event", {"outcome": "success", "auth_type": "ssh", "principal": "bob"}),
        ("dns_query", {"client_ip": "1.1.1.1", "query_name": "x.com", "query_type": "A"}),
        ("process_exec", {"host": "h", "process_name": "p"}),
        ("file_access", {"host": "h", "path": "/p", "action": "write"}),
    ]
    for src, fields in cases:
        await rig.engine.handle(
            make_record_fn(make_envelope_fn(src, **fields).model_dump_json().encode())
        )
    assert len(rig.producer.to(CANONICAL_TOPIC)) == len(cases)
    assert not rig.producer.to(DLQ_TOPIC)
