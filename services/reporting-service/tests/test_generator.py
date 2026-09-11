from __future__ import annotations

import uuid
from typing import Any

import pytest

from .conftest import detection, threat_score

pytestmark = pytest.mark.asyncio


async def test_complete_report_from_a_detection_subject(
    generator: Any, content_repo: Any, content: Any,
):
    tenant_id = uuid.uuid4()
    det = detection(tenant_id)
    content_repo.detection_response = det
    content_repo.score_response = threat_score(tenant_id)
    content.techniques_response = [{"technique_id": "T1110", "name": "Brute Force"}]
    content.memory_patterns_response = [{"id": str(uuid.uuid4()), "technique_ids": ["T1110"], "occurrence_count": 3}]
    content.lateral_movement_response = {
        "kind": "lateral_movement", "subject_type": "host", "subject_id": "web02",
        "prediction": "host:web02", "confidence": 0.7, "evidence": [], "features": {},
        "model_version": "heuristic-v1", "generated_at": "2026-01-01T00:00:00Z",
    }
    content.explain_response = {
        "subject_type": "detection", "subject_id": str(det.id), "summary": "Repeated failed logins.",
        "cited_refs": [], "confidence": "medium", "recommendations": ["Rotate credentials"],
        "model": {}, "generated_at": "2026-01-01T00:00:00Z", "degraded": False,
        "degraded_reason": "", "prompt_injection_detected": False,
    }

    report = await generator.generate(
        tenant_id, kind="incident", subject_type="detection", subject_id=str(det.id),
        title="Incident report", requested_by=uuid.uuid4(),
    )

    assert report.status == "complete"
    assert report.missing_sections == []
    assert report.detection_ids == [str(det.id)]
    assert report.technique_ids == ["T1110"]
    assert report.threat_score == 0.6
    assert "detection-engine" in report.provenance
    assert "mitre-service" in report.provenance
    assert "memory-service" in report.provenance
    assert "ai-analyst" in report.provenance
    assert report.storage_key is not None


async def test_evidence_is_tagged_evidence_tier(generator: Any, content_repo: Any):
    tenant_id = uuid.uuid4()
    det = detection(tenant_id)
    content_repo.detection_response = det

    report = await generator.generate(
        tenant_id, kind="incident", subject_type="detection", subject_id=str(det.id),
        title="t", requested_by=uuid.uuid4(),
    )

    assert report.evidence
    assert all(e.tier.value == "evidence" for e in report.evidence)


async def test_lateral_movement_prediction_is_tagged_prediction_tier(
    generator: Any, content: Any,
):
    tenant_id = uuid.uuid4()
    content.lateral_movement_response = {
        "kind": "lateral_movement", "subject_type": "host", "subject_id": "web02",
        "prediction": "host:web02", "confidence": 0.9, "evidence": [], "features": {},
        "model_version": "heuristic-v1", "generated_at": "2026-01-01T00:00:00Z",
    }

    report = await generator.generate(
        tenant_id, kind="incident", subject_type="host", subject_id="web01",
        title="t", requested_by=uuid.uuid4(),
    )

    predicted = [f for f in report.findings if f.tier.value == "prediction"]
    assert len(predicted) == 1
    assert "web02" in predicted[0].text


async def test_zero_confidence_prediction_is_not_reported_as_a_finding(
    generator: Any, content: Any,
):
    """`confidence == 0.0` means the model could not support a prediction —
    never present as a result (mirrors `sm_ml.predict`'s own convention)."""
    tenant_id = uuid.uuid4()
    content.lateral_movement_response = {
        "kind": "lateral_movement", "subject_type": "host", "subject_id": "none",
        "prediction": "none — no other fingerprint recorded", "confidence": 0.0,
        "evidence": [], "features": {}, "model_version": "heuristic-v1",
        "generated_at": "2026-01-01T00:00:00Z",
    }

    report = await generator.generate(
        tenant_id, kind="incident", subject_type="host", subject_id="web01",
        title="t", requested_by=uuid.uuid4(),
    )

    assert not any(f.tier.value == "prediction" for f in report.findings)


async def test_ai_analyst_is_only_called_for_a_detection_subject(generator: Any, content: Any):
    content.explain_response = {
        "subject_type": "detection", "subject_id": "x", "summary": "should not appear",
        "cited_refs": [], "confidence": "low", "recommendations": [], "model": {},
        "generated_at": "2026-01-01T00:00:00Z", "degraded": False, "degraded_reason": "",
        "prompt_injection_detected": False,
    }

    report = await generator.generate(
        uuid.uuid4(), kind="incident", subject_type="host", subject_id="web01",
        title="t", requested_by=uuid.uuid4(),
    )

    assert "ai-analyst" not in report.provenance
    assert not any(f.tier.value == "inference" for f in report.findings)


async def test_unreachable_content_dependency_marks_the_report_partial(
    generator: Any, content: Any, repo: Any,
):
    repo.template_sections_response["incident"] = [
        "metadata", "affected_assets", "evidence", "findings",
    ]
    content.graph_raises = True

    report = await generator.generate(
        uuid.uuid4(), kind="incident", subject_type="host", subject_id="web01",
        title="t", requested_by=uuid.uuid4(),
    )

    assert report.status == "partial"
    assert "affected_assets" in report.missing_sections


async def test_missing_section_not_flagged_when_the_templates_kind_omits_it(
    generator: Any, content: Any, repo: Any,
):
    """`executive_summary` never asks for `affected_assets` — a graph-service
    outage should not make that kind of report `partial`."""
    repo.template_sections_response["executive_summary"] = ["metadata", "findings"]
    content.graph_raises = True

    report = await generator.generate(
        uuid.uuid4(), kind="executive_summary", subject_type="host", subject_id="web01",
        title="t", requested_by=uuid.uuid4(),
    )

    assert report.status == "complete"
    assert report.missing_sections == []


async def test_object_storage_failure_marks_the_report_failed_and_no_event_is_sent(
    generator: Any, store: Any, producer: Any,
):
    store.put_raises = True

    report = await generator.generate(
        uuid.uuid4(), kind="incident", subject_type="host", subject_id="web01",
        title="t", requested_by=uuid.uuid4(),
    )

    assert report.status == "failed"
    assert report.storage_key is None
    assert producer.sent == []


async def test_report_generated_event_is_produced_on_success(generator: Any, producer: Any):
    tenant_id = uuid.uuid4()
    report = await generator.generate(
        tenant_id, kind="incident", subject_type="host", subject_id="web01",
        title="t", requested_by=uuid.uuid4(),
    )

    assert len(producer.sent) == 1
    topic, key, value = producer.sent[0]
    assert topic == "report.generated"
    assert key  # a real sha256-derived partition key, not a fixed/empty string
    assert str(tenant_id).encode() in value
    assert str(report.id).encode() in value
