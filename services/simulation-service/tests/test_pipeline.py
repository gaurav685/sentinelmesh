from __future__ import annotations

import uuid

from sm_simulation_service.pipeline import feed_events

from sm_ml.scenario import SimEvent, SimEventKind, build_synthetic_env

from .conftest import FakeProducer

_ENV = build_synthetic_env(seed=1)


async def test_feed_events_sends_one_envelope_per_mappable_event() -> None:
    producer = FakeProducer()
    events = (
        SimEvent(
            step=0, at_offset_s=0, kind=SimEventKind.auth_failed, actor="sim-ip-00",
            target="sim-id-alice", attributes={"reason": "bad_password"}, scenario_id="scn-1",
        ),
        SimEvent(
            step=1, at_offset_s=1, kind=SimEventKind.network_flow, actor="sim-ip-00",
            target="sim-ip-01", attributes={}, scenario_id="scn-1",
        ),
    )
    sent = await feed_events(producer, uuid.uuid4(), "scn-1", events, _ENV)
    assert sent == 2
    assert len(producer.sent) == 2
    assert all(topic == "telemetry.raw" for topic, _key, _value in producer.sent)


async def test_feed_events_uses_synthetic_entity_names() -> None:
    producer = FakeProducer()
    events = (
        SimEvent(
            step=0, at_offset_s=0, kind=SimEventKind.network_flow, actor="sim-ip-00",
            target="sim-ip-01", attributes={}, scenario_id="scn-1",
        ),
    )
    await feed_events(producer, uuid.uuid4(), "scn-1", events, _ENV)
    _topic, _key, value = producer.sent[0]
    src_ip = _ENV.get("sim-ip-00")
    dst_ip = _ENV.get("sim-ip-01")
    assert src_ip is not None and dst_ip is not None
    assert src_ip.name.encode("utf-8") in value
    assert dst_ip.name.encode("utf-8") in value


async def test_feed_events_marks_every_envelope_as_simulation_sourced() -> None:
    producer = FakeProducer()
    events = (
        SimEvent(
            step=0, at_offset_s=0, kind=SimEventKind.process_exec, actor="sim-host-00",
            target="sim-id-alice", attributes={"cmd": "whoami"}, scenario_id="scn-1",
        ),
    )
    await feed_events(producer, uuid.uuid4(), "scn-1", events, _ENV)
    _topic, _key, value = producer.sent[0]
    assert b'"type":"simulation"' in value
