from __future__ import annotations

import json

import pytest
from sm_mitre_service.engine import MappingHandler

from sm_common.bus import PoisonError, TransientError

from .conftest import FakeMappingDb, detection_payload, detection_record


async def test_maps_a_detections_candidate_techniques(
    handler: tuple[MappingHandler, FakeMappingDb],
) -> None:
    h, db = handler
    await h.handle(detection_record(detection_payload(technique_ids=["T1110", "T404"])))
    # one write for the mapped technique, none for the unmapped one
    assert len(db.executed) == 1


async def test_no_candidate_techniques_is_a_noop(
    handler: tuple[MappingHandler, FakeMappingDb],
) -> None:
    h, db = handler
    await h.handle(detection_record(detection_payload(technique_ids=[])))
    assert db.executed == []


async def test_not_a_detection_record_is_poison(handler: tuple[MappingHandler, FakeMappingDb]) -> None:
    from aiokafka.structs import ConsumerRecord

    h, _ = handler
    bad = json.dumps({"event_type": "graph.command"}).encode()
    rec = ConsumerRecord(
        topic="detections", partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=b"k", value=bad, checksum=None, serialized_key_size=0,
        serialized_value_size=len(bad), headers=(),
    )
    with pytest.raises(PoisonError, match=r"not a detection\.raised"):
        await h.handle(rec)


async def test_db_failure_is_transient(handler: tuple[MappingHandler, FakeMappingDb]) -> None:
    h, db = handler

    def _boom(*_a: object, **_kw: object) -> None:
        raise RuntimeError("db down")

    db.transaction = _boom  # type: ignore[method-assign]
    with pytest.raises(TransientError, match="technique_mapping write failed"):
        await h.handle(detection_record(detection_payload(technique_ids=["T1110"])))
