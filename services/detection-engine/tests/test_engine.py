from __future__ import annotations

import json

import pytest

from sm_common.bus import PoisonError, TransientError
from sm_contracts import CanonicalKind

from .conftest import Rig, anomaly_score, canonical, record_for, warm


async def test_not_a_canonical_record_is_poison(rig: Rig) -> None:
    from aiokafka.structs import ConsumerRecord

    bad = json.dumps({"event_type": "graph.command"}).encode()
    rec = ConsumerRecord(
        topic="events.canonical", partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=b"k", value=bad, checksum=None, serialized_key_size=0,
        serialized_value_size=len(bad), headers=(),
    )
    with pytest.raises(PoisonError, match=r"not an event\.canonical"):
        await rig.engine.handle(rec)


async def test_warming_up_writes_no_anomaly_and_no_detection(rig: Rig) -> None:
    for _ in range(5):  # below detection_min_samples (10)
        env = canonical(CanonicalKind.network_flow, actor=("host", "h"), target=("ip", "10.0.0.1"),
                        action="connected_to", attributes={"bytes_sent": 100, "protocol": "tcp"})
        await rig.engine.handle(record_for(env))
    assert rig.repo.anomalies == []
    assert rig.repo.detections == []


async def test_outlier_after_warmup_raises_a_detection(rig: Rig) -> None:
    await warm(rig, CanonicalKind.network_flow, 15, bytes_sent=100, protocol="tcp")
    rig.repo.anomalies.clear()

    spike = canonical(CanonicalKind.network_flow, actor=("host", "h9"), target=("ip", "9.9.9.9"),
                      action="connected_to",
                      attributes={"bytes_sent": 10**9, "protocol": "tcp", "direction": "outbound"})
    await rig.engine.handle(record_for(spike))

    assert any(a["method"] == "mad_zscore" for a in rig.repo.anomalies)
    assert rig.repo.detections, "an outlier should produce a detection"
    det = rig.repo.detections[-1]
    assert det["scoring_status"] == "degraded"  # no ml-inference model
    assert det["evidence"]
    assert rig.producer.detections()


async def test_a_rule_hit_alone_raises_a_detection_without_warmup(rig: Rig) -> None:
    for _ in range(5):
        env = canonical(CanonicalKind.auth, outcome="failure", actor=("identity", "mallory"),
                        action="authentication_failed")
        await rig.engine.handle(record_for(env))
    det = rig.repo.detections[-1]
    assert det["rule_id"] == "rule.auth.failed_burst"
    assert "T1110" in det["technique_ids"]
    assert rig.producer.detections()[-1]["payload"]["detector"] in {"rule", "composite"}


async def test_model_contribution_makes_scoring_ok(rig: Rig) -> None:
    rig.inference._score = anomaly_score(normalized=0.9, is_anomaly=True)
    await warm(rig, CanonicalKind.network_flow, 15, bytes_sent=100, protocol="tcp")
    spike = canonical(CanonicalKind.network_flow, actor=("host", "h9"), target=("ip", "9.9.9.9"),
                      action="connected_to", attributes={"bytes_sent": 10**9, "protocol": "tcp"})
    await rig.engine.handle(record_for(spike))
    det = rig.repo.detections[-1]
    assert det["scoring_status"] == "ok"
    assert any(a["method"] == "isolation_forest" for a in rig.repo.anomalies)


async def test_high_severity_opens_an_alert(rig: Rig) -> None:
    for _ in range(16):  # 15+ failures -> high
        env = canonical(CanonicalKind.auth, outcome="failure", actor=("identity", "x"),
                        action="authentication_failed")
        await rig.engine.handle(record_for(env))
    assert rig.repo.alerts


async def test_reprocess_updates_one_detection_id(rig: Rig) -> None:
    for _ in range(5):
        env = canonical(CanonicalKind.auth, outcome="failure", actor=("identity", "y"),
                        action="authentication_failed", occurred_at=None)
        await rig.engine.handle(record_for(env))
    ids = {d["detection_id"] for d in rig.repo.detections}
    assert len(ids) == 1


async def test_tenant_windows_are_isolated(rig: Rig) -> None:
    import uuid

    t2 = uuid.uuid4()
    await warm(rig, CanonicalKind.network_flow, 15, bytes_sent=100, protocol="tcp")
    # tenant 2's first event must still be "warming up" — separate window
    env = canonical(CanonicalKind.network_flow, actor=("host", "z"), target=("ip", "1.1.1.1"),
                    action="connected_to", attributes={"bytes_sent": 10**9, "protocol": "tcp"},
                    tenant_id=t2)
    n_before = len(rig.repo.anomalies)
    await rig.engine.handle(record_for(env))
    assert len(rig.repo.anomalies) == n_before  # nothing scored for the cold tenant


async def test_db_failure_is_transient(rig: Rig) -> None:
    await warm(rig, CanonicalKind.network_flow, 12, bytes_sent=100, protocol="tcp")
    rig.repo.fail_on = "anomaly"
    with pytest.raises(TransientError, match="anomaly write failed"):
        env = canonical(CanonicalKind.network_flow, actor=("host", "h"), target=("ip", "10.0.0.1"),
                        action="connected_to", attributes={"bytes_sent": 999, "protocol": "tcp"})
        await rig.engine.handle(record_for(env))


async def test_produce_failure_is_transient(rig: Rig) -> None:
    rig.producer.fail = True
    # prime the burst rule, then the 5th failure tries (and fails) to emit
    for _ in range(4):
        await rig.engine.handle(record_for(canonical(
            CanonicalKind.auth, outcome="failure", actor=("identity", "q"),
            action="authentication_failed",
        )))
    with pytest.raises(TransientError, match="produce to detections"):
        await rig.engine.handle(record_for(canonical(
            CanonicalKind.auth, outcome="failure", actor=("identity", "q"),
            action="authentication_failed",
        )))
