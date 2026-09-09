from __future__ import annotations

import json

import pytest
from aiokafka.structs import ConsumerRecord
from sm_correlation_engine.engine import CorrelationHandler

from sm_common.bus import PoisonError, TransientError
from sm_contracts import ThreatSubjectType

from .conftest import FakeChainRepo, FakeProducer, detection_payload, record_for


def _handler(repo: FakeChainRepo, producer: FakeProducer) -> CorrelationHandler:
    from sm_correlation_engine.metrics import CorrelationMetrics

    from sm_common.observability import build_metrics

    return CorrelationHandler(
        repo=repo, producer=producer,  # type: ignore[arg-type]
        metrics=CorrelationMetrics(build_metrics("correlation-engine"), "correlation-engine"),
    )


async def test_handle_correlates_and_emits_an_attack_chain_event() -> None:
    repo, producer = FakeChainRepo(), FakeProducer()
    await _handler(repo, producer).handle(record_for(detection_payload(technique_ids=["T1110"])))

    assert repo.calls and repo.calls[0][1] is ThreatSubjectType.identity
    chains = producer.chains()
    assert len(chains) == 1
    assert chains[0].subject_id == "alice"


async def test_handle_also_projects_the_chain_onto_graph_commands() -> None:
    repo, producer = FakeChainRepo(), FakeProducer()
    await _handler(repo, producer).handle(record_for(detection_payload(technique_ids=["T1110"])))
    topics = [t for t, _ in producer.sent]
    assert "attack_chains" in topics
    assert "graph.commands" in topics


async def test_a_record_that_is_not_a_detection_is_poison() -> None:
    repo, producer = FakeChainRepo(), FakeProducer()
    bad = ConsumerRecord(
        topic="detections", partition=0, offset=0, timestamp=0, timestamp_type=0, key=b"k",
        value=json.dumps({"event_type": "telemetry.raw"}).encode(), checksum=None,
        serialized_key_size=0, serialized_value_size=0, headers=(),
    )
    with pytest.raises(PoisonError):
        await _handler(repo, producer).handle(bad)


async def test_unparseable_record_is_poison() -> None:
    repo, producer = FakeChainRepo(), FakeProducer()
    bad = ConsumerRecord(
        topic="detections", partition=0, offset=0, timestamp=0, timestamp_type=0, key=b"k",
        value=b"not json", checksum=None, serialized_key_size=0, serialized_value_size=0, headers=(),
    )
    with pytest.raises(PoisonError):
        await _handler(repo, producer).handle(bad)


async def test_a_repo_failure_is_retryable() -> None:
    repo, producer = FakeChainRepo(), FakeProducer()
    repo.fail = True
    with pytest.raises(TransientError):
        await _handler(repo, producer).handle(record_for(detection_payload()))


async def test_a_failed_produce_is_retryable() -> None:
    repo, producer = FakeChainRepo(), FakeProducer()
    producer.fail = True
    with pytest.raises(TransientError):
        await _handler(repo, producer).handle(record_for(detection_payload()))
