from __future__ import annotations

import json
from typing import Any

import pytest
from aiokafka.structs import ConsumerRecord

from sm_common.bus.processor import PoisonError, RecordProcessor, _peek_trace_id
from sm_common.observability import build_metrics


def _record(value: bytes, *, topic: str = "detections") -> ConsumerRecord:
    return ConsumerRecord(
        topic=topic, partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=b"k", value=value, checksum=None, serialized_key_size=0,
        serialized_value_size=len(value), headers=(),
    )


def test_peek_trace_id_reads_a_well_formed_envelope() -> None:
    value = json.dumps({"trace_id": "aa" * 16, "event_id": "e1"}).encode()
    assert _peek_trace_id(_record(value)) == "aa" * 16


def test_peek_trace_id_none_when_field_missing() -> None:
    value = json.dumps({"event_id": "e1"}).encode()
    assert _peek_trace_id(_record(value)) is None


def test_peek_trace_id_none_when_field_is_the_wrong_type() -> None:
    value = json.dumps({"trace_id": 12345}).encode()
    assert _peek_trace_id(_record(value)) is None


def test_peek_trace_id_none_on_malformed_json_never_raises() -> None:
    assert _peek_trace_id(_record(b"not json at all")) is None


class FakeProducer:
    async def send(self, topic: str, *, key: str, value: bytes) -> None:
        return None


@pytest.mark.asyncio
async def test_call_still_invokes_handle_and_wraps_the_span_regardless_of_trace_id() -> None:
    """A missing/malformed trace_id must never block normal processing — the
    span link is best-effort observability, not a required precondition."""
    seen: list[ConsumerRecord] = []

    async def handle(record: ConsumerRecord) -> None:
        seen.append(record)

    processor = RecordProcessor(
        producer=FakeProducer(), consumer_group="g", handle=handle,  # type: ignore[arg-type]
        metrics=build_metrics("svc"), service_name="svc",
    )

    good = _record(json.dumps({"trace_id": "bb" * 16}).encode())
    bad = _record(b"not json")
    await processor(good)
    await processor(bad)
    assert seen == [good, bad]


@pytest.mark.asyncio
async def test_poison_error_still_dead_letters_with_a_malformed_trace_id() -> None:
    async def handle(_record: ConsumerRecord) -> None:
        raise PoisonError("bad payload")

    sent: list[tuple[str, Any]] = []

    class _CapturingProducer:
        async def send(self, topic: str, *, key: str, value: bytes) -> None:
            sent.append((topic, value))

    processor = RecordProcessor(
        producer=_CapturingProducer(), consumer_group="g", handle=handle,  # type: ignore[arg-type]
        metrics=build_metrics("svc"), service_name="svc",
    )
    await processor(_record(b"garbage"))
    assert sent and sent[0][0] == "detections.dlq"
