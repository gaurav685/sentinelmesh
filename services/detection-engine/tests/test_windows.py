from __future__ import annotations

import uuid

from sm_detection_engine.windows import EventTimeline, FeatureWindows

from sm_contracts import CanonicalKind

_T = uuid.uuid4()


def test_feature_window_is_capped_and_per_key() -> None:
    w = FeatureWindows(size=3)
    for i in range(5):
        w.observe(_T, CanonicalKind.auth, [float(i)])
    assert w.sample(_T, CanonicalKind.auth) == [[2.0], [3.0], [4.0]]
    assert w.sample(_T, CanonicalKind.dns) == []
    assert w.size(uuid.uuid4(), CanonicalKind.auth) == 0


def test_timeline_prunes_old_entries() -> None:
    tl = EventTimeline(window_s=100)
    tl.record(_T, "alice", "authfail", at=1000.0)
    tl.record(_T, "alice", "authfail", at=1050.0)
    assert tl.count(_T, "authfail", "alice", at=1120.0) == 1  # the 1000.0 one aged out
    assert tl.count(_T, "authfail", "alice", at=1200.0) == 0


def test_timeline_subjects_by_tag() -> None:
    tl = EventTimeline(window_s=300)
    tl.record(_T, "a|web01", "authok", at=1.0)
    tl.record(_T, "a|web02", "authok", at=2.0)
    tl.record(_T, "b|web01", "authok", at=3.0)
    assert tl.subjects(_T, "authok", at=10.0) == {"a|web01", "a|web02", "b|web01"}
