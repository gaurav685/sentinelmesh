from __future__ import annotations

import pytest

from sm_ml.temporal import (
    EventTimeline,
    ReplayCursor,
    Session,
    TemporalEvent,
    TemporalGraphState,
    build_progression,
    replay,
    stitch_sessions,
)


def _ev(eid: str, occurred: float, *, ingested: float | None = None, entities=(), kind="auth",
        session: str | None = None) -> TemporalEvent:
    return TemporalEvent(
        event_id=eid, occurred_at=occurred, ingested_at=ingested if ingested is not None else occurred,
        kind=kind, entities=tuple(entities), session_id=session,
    )


# ---- timeline: ordering / duplicate / skew / gaps -----------------
def test_out_of_order_events_are_sorted_and_order_independent() -> None:
    a = EventTimeline()
    a.extend([_ev("e2", 20), _ev("e1", 10), _ev("e3", 30)])
    b = EventTimeline()
    b.extend([_ev("e3", 30), _ev("e1", 10), _ev("e2", 20)])
    assert [e.event_id for e in a] == ["e1", "e2", "e3"]
    assert a.events() == b.events()


def test_duplicate_event_ids_are_dropped() -> None:
    tl = EventTimeline()
    assert tl.add(_ev("e1", 10)) is True
    assert tl.add(_ev("e1", 999)) is False  # same id, different time -> ignored
    assert len(tl) == 1
    assert tl.duplicates_dropped == 1


def test_clock_skew_is_clamped_and_counted() -> None:
    tl = EventTimeline(max_skew_seconds=60.0)
    tl.add(_ev("skewed", occurred=10_000.0, ingested=100.0))  # 9900s ahead of ingest
    tl.add(_ev("ok", occurred=120.0, ingested=120.0))
    assert tl.skew_corrected == 1
    # the skewed event is clamped to ingested + 60 = 160, so it sorts AFTER "ok"
    assert [e.event_id for e in tl] == ["ok", "skewed"]


def test_gaps_reports_long_silences() -> None:
    tl = EventTimeline()
    tl.extend([_ev("a", 0), _ev("b", 5), _ev("c", 5000)])
    gaps = tl.gaps(threshold_seconds=100)
    assert len(gaps) == 1
    assert gaps[0].after_event_id == "b" and gaps[0].before_event_id == "c"


# ---- temporal graph state --------------------------------------
def test_graph_state_at_a_time_is_a_pure_fold() -> None:
    tl = EventTimeline()
    tl.extend([
        _ev("e1", 10, entities=("alice", "host1")),
        _ev("e2", 20, entities=("alice", "host2")),
        _ev("e3", 30, entities=("bob", "host2")),
    ])

    def edges(e: TemporalEvent):  # type: ignore[no-untyped-def]
        return [(e.entities[0], e.entities[1], "TOUCHED")] if len(e.entities) == 2 else []

    state = TemporalGraphState.from_timeline(tl, edge_fn=edges)
    early = state.at(15)
    assert {n.node_id for n in early.nodes} == {"alice", "host1"}
    late = state.at(25)
    assert {n.node_id for n in late.nodes} == {"alice", "host1", "host2"}
    assert state.at(25) == state.at(25)  # deterministic


# ---- progression --------------------------------------------
def test_progression_never_regresses_but_records_every_transition() -> None:
    from sm_contracts import AttackStage

    tl = EventTimeline()
    tl.extend([_ev("a", 1), _ev("b", 2), _ev("c", 3), _ev("d", 4)])
    stages = {
        "a": AttackStage.credential_access,   # order 7
        "b": AttackStage.lateral_movement,    # order 9 -> advance
        "c": AttackStage.reconnaissance,      # order 0 -> not an advance
        "d": AttackStage.exfiltration,        # order 12 -> advance
    }
    track = build_progression(tl, lambda e: stages[e.event_id])
    assert [p.furthest_stage for p in track.points] == [
        AttackStage.credential_access, AttackStage.lateral_movement,
        AttackStage.lateral_movement, AttackStage.exfiltration,
    ]
    assert [p.event_id for p in track.advances()] == ["a", "b", "d"]
    assert track.furthest_stage_at(2.5) is AttackStage.lateral_movement


# ---- replay -------------------------------------------------
def test_replay_is_deterministic_and_windowed() -> None:
    tl = EventTimeline()
    tl.extend([_ev(f"e{i}", float(i)) for i in range(10)])
    assert [e.event_id for e in replay(tl, 3.0, 6.0)] == ["e3", "e4", "e5", "e6"]

    cur = ReplayCursor(tl, from_t=0.0, to_t=4.0)
    assert len(cur) == 5
    assert [e.event_id for e in cur.next(2)] == ["e0", "e1"]
    assert cur.remaining == 3
    cur.reset()
    assert cur.remaining == 5
    with pytest.raises(ValueError):
        list(replay(tl, 6.0, 3.0))


# ---- cross-session stitching --------------------------------
def test_sessions_are_stitched_by_shared_entity_and_time_proximity() -> None:
    s1 = Session("s1", frozenset({"alice", "h1"}), start=0.0, end=100.0)
    s2 = Session("s2", frozenset({"alice", "h2"}), start=200.0, end=300.0)   # shares alice, +100s gap
    s3 = Session("s3", frozenset({"carol"}), start=250.0, end=400.0)         # unrelated
    s4 = Session("s4", frozenset({"h2"}), start=100_000.0, end=100_100.0)    # shares h2 but far away

    tracks = stitch_sessions([s3, s1, s4, s2], link_within_seconds=3600.0)
    by_sessions = {t.session_ids for t in tracks}
    assert ("s1", "s2") in by_sessions
    assert ("s3",) in by_sessions
    assert ("s4",) in by_sessions
    # deterministic
    assert stitch_sessions([s1, s2, s3, s4], link_within_seconds=3600.0) == tracks


def test_stitch_rejects_an_inverted_session() -> None:
    with pytest.raises(ValueError):
        Session("bad", frozenset({"x"}), start=10.0, end=5.0)
