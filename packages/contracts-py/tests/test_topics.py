from __future__ import annotations

import pytest

from sm_contracts import (
    EVENT_TYPE_TOPIC,
    EVENT_TYPE_VERSION,
    TOPICS,
    EventType,
    dlq_topic,
    replay_group,
    topic_for_event_type,
)


def test_every_event_type_maps_to_a_defined_topic() -> None:
    for event_type in EventType:
        topic = EVENT_TYPE_TOPIC[event_type]  # KeyError = an unmapped member
        assert topic in TOPICS, f"{event_type} -> {topic} not in the catalog"


def test_topic_for_event_type_matches_the_mapping() -> None:
    assert topic_for_event_type(EventType.event_canonical) == "events.canonical"
    assert topic_for_event_type(EventType.telemetry_dns_query) == "telemetry.raw"


def test_all_telemetry_types_share_one_topic() -> None:
    telemetry = {topic_for_event_type(t) for t in EventType if t.value.startswith("telemetry.")}
    assert telemetry == {"telemetry.raw"}


def test_catalog_invariants() -> None:
    for spec in TOPICS.values():
        assert spec.partitions >= 1
        assert spec.partitions_min == spec.partitions
        assert spec.cleanup in ("delete", "compact")
        assert spec.producers and spec.consumer_groups
        if spec.retention == "compact":
            assert spec.cleanup == "compact"
            assert spec.retention_ms is None
        else:
            assert spec.retention.endswith("d")
            assert spec.retention_ms == int(spec.retention[:-1]) * 86_400_000


def test_key_partition_counts_match_the_event_model() -> None:
    # event-model.md §3 — a regression guard on the numbers that matter.
    expected = {
        "telemetry.raw": 12, "events.canonical": 24, "graph.commands": 12,
        "detections": 12, "attack_chains": 6, "user.events": 3,
    }
    for name, partitions in expected.items():
        assert TOPICS[name].partitions == partitions


def test_dlq_and_replay_helpers() -> None:
    assert dlq_topic("events.canonical") == "events.canonical.dlq"
    assert replay_group("detection") == "detection-replay"


def test_every_event_type_has_a_version() -> None:
    assert set(EVENT_TYPE_VERSION) == set(EventType)
    assert set(EVENT_TYPE_VERSION.values()) == {1}  # all v1 today


def test_no_event_type_string_carries_a_version_suffix_yet() -> None:
    for event_type in EventType:
        assert not event_type.value.endswith((".v2", ".v3"))


def test_user_events_has_no_dlq() -> None:
    assert TOPICS["user.events"].has_dlq is False
    assert TOPICS["events.canonical"].has_dlq is True


def test_unmapped_event_type_raises_keyerror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(EVENT_TYPE_TOPIC, EventType.event_canonical, raising=False)
    with pytest.raises(KeyError):
        topic_for_event_type(EventType.event_canonical)
