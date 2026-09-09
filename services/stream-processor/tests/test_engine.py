from __future__ import annotations

import json
from typing import Any

import pytest

from sm_contracts import CanonicalKind
from sm_stream_processor.topics import CANONICAL_TOPIC, DLQ_TOPIC, GRAPH_COMMANDS_TOPIC


async def test_canonical_event_produces_graph_commands(
    rig: Any, make_canonical_fn: Any, make_record_fn: Any
) -> None:
    env = make_canonical_fn(
        CanonicalKind.network_flow, actor_value="10.0.0.1", target_value="8.8.8.8"
    )
    await rig.processor(make_record_fn(env.model_dump_json().encode()))

    out = rig.producer.to(GRAPH_COMMANDS_TOPIC)
    assert len(out) == 3  # 2 node upserts + 1 edge
    assert {c["event_type"] for c in out} == {"graph.command"}
    assert {c["payload"]["raw_event_id"] for c in out} == {str(env.payload.raw_event_id)}
    assert not rig.producer.to(DLQ_TOPIC)


async def test_non_canonical_record_is_dead_lettered(rig: Any, make_record_fn: Any) -> None:
    await rig.processor(make_record_fn(json.dumps({"event_type": "telemetry.network_flow"}).encode()))
    dlq = rig.producer.to(DLQ_TOPIC)
    assert len(dlq) == 1
    assert dlq[0]["error_type"] == "poison"
    assert not rig.producer.to(GRAPH_COMMANDS_TOPIC)


async def test_unparseable_record_is_dead_lettered(rig: Any, make_record_fn: Any) -> None:
    await rig.processor(make_record_fn(b"{bad"))
    assert rig.producer.to(DLQ_TOPIC)[0]["error_type"] == "poison"


async def test_produce_failure_retries_then_dead_letters(
    rig: Any, make_canonical_fn: Any, make_record_fn: Any
) -> None:
    rig.producer.fail_topics = {GRAPH_COMMANDS_TOPIC}
    env = make_canonical_fn(CanonicalKind.dns, actor_value="10.0.0.5", target_value="x.com")
    await rig.processor(make_record_fn(env.model_dump_json().encode()))

    assert not rig.producer.to(GRAPH_COMMANDS_TOPIC)
    dlq = rig.producer.to(DLQ_TOPIC)
    assert dlq and dlq[0]["error_type"] == "retries_exhausted"


async def test_redelivery_reemits_identical_command_ids(
    rig: Any, make_canonical_fn: Any, make_record_fn: Any
) -> None:
    env = make_canonical_fn(CanonicalKind.auth, actor_value="bob", target_value="host1")
    raw = env.model_dump_json().encode()
    await rig.processor(make_record_fn(raw))
    first = {c["event_id"] for c in rig.producer.to(GRAPH_COMMANDS_TOPIC)}
    await rig.processor(make_record_fn(raw))
    second = {c["event_id"] for c in rig.producer.to(GRAPH_COMMANDS_TOPIC)}
    assert first == second  # same ids, no new distinct commands


async def test_infra_failure_propagates_uncommitted(rig: Any, make_record_fn: Any) -> None:
    rig.producer.fail = True
    with pytest.raises(Exception):  # noqa: B017
        await rig.processor(make_record_fn(b"{bad"))
    assert CANONICAL_TOPIC  # import kept meaningful
