from __future__ import annotations

import json

import pytest

from sm_common.bus import PoisonError, TransientError
from sm_graph_service.topics import EVENTS_TOPIC

from .conftest import envelope_for, make_record, node_command


def _record_for(cmd) -> object:  # type: ignore[no-untyped-def]
    return make_record(envelope_for(cmd).model_dump_json().encode("utf-8"))


async def test_applies_command_and_emits_one_graph_event(rig) -> None:  # type: ignore[no-untyped-def]
    cmd = node_command()
    await rig.engine.handle(_record_for(cmd))

    events = rig.producer.to(EVENTS_TOPIC)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_id"] == str(cmd.command_id)
    assert ev["event_type"] == "graph.event"
    assert ev["payload"]["outcome"] == "APPLIED"
    assert ev["payload"]["command_id"] == str(cmd.command_id)
    assert ev["payload"]["nodes_written"] == 1


async def test_duplicate_still_emits_a_graph_event_with_duplicate_outcome(rig) -> None:  # type: ignore[no-untyped-def]
    cmd = node_command()
    rig.graph.applied_ids.add(str(cmd.command_id))
    await rig.engine.handle(_record_for(cmd))
    assert rig.producer.to(EVENTS_TOPIC)[0]["payload"]["outcome"] == "DUPLICATE"


async def test_not_a_graph_command_envelope_is_poison(rig) -> None:  # type: ignore[no-untyped-def]
    bad = json.dumps({"event_type": "event.canonical"}).encode("utf-8")
    with pytest.raises(PoisonError, match=r"not a graph\.command"):
        await rig.engine.handle(make_record(bad))


async def test_unparseable_record_is_poison(rig) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(PoisonError, match="unparseable"):
        await rig.engine.handle(make_record(b"{not json"))


async def test_neo4j_unavailable_is_transient(rig) -> None:  # type: ignore[no-untyped-def]
    rig.graph.unavailable = True
    with pytest.raises(TransientError, match="neo4j unavailable"):
        await rig.engine.handle(_record_for(node_command()))


async def test_failed_produce_to_graph_events_is_transient(rig) -> None:  # type: ignore[no-untyped-def]
    rig.producer.fail_topics = {EVENTS_TOPIC}
    with pytest.raises(TransientError, match="produce to"):
        await rig.engine.handle(_record_for(node_command()))
