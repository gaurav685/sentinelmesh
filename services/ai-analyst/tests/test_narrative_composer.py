from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sm_ai import DeterministicAdapter
from sm_ai.errors import ProviderUnavailable
from sm_ai_analyst.narrative import NarrativeComposer
from sm_contracts import AttackChainModel, ChainStageModel, GroundingKind

from .conftest import build_client, canned_client, scripted_provider_raising

_NOW = datetime.now(UTC)


def _chain(*, subject_id: str = "web01", stages: list[ChainStageModel] | None = None) -> AttackChainModel:
    if stages is None:
        stages = [
            ChainStageModel(
                stage="initial_access", stage_order=2, detection_ids=[str(uuid.uuid4())],
                technique_ids=["T1110"], max_severity="high", max_detection_score=0.8,
                detection_count=1, first_seen=_NOW, last_seen=_NOW,
            ),
            ChainStageModel(
                stage="lateral_movement", stage_order=9, detection_ids=[str(uuid.uuid4())],
                technique_ids=["T1021"], max_severity="medium", max_detection_score=0.6,
                detection_count=1, first_seen=_NOW, last_seen=_NOW,
            ),
        ]
    return AttackChainModel(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), created_at=_NOW, updated_at=_NOW,
        subject_type="host", subject_id=subject_id, status="active", window_start=_NOW,
        first_seen=_NOW, last_seen=_NOW, stages=stages, distinct_stage_count=len(stages),
        progression=0.5, confidence=0.6, score=0.5, score_version="v1", scoring_status="ok",
        technique_ids=[t for s in stages for t in s.technique_ids],
        detection_count=sum(s.detection_count for s in stages),
    )


def _composer(client: object | None) -> NarrativeComposer:
    return NarrativeComposer(client, model="test-model", max_output_tokens=500)  # type: ignore[arg-type]


async def test_beats_are_deterministic_from_the_chains_own_stages() -> None:
    chain = _chain()
    body = await _composer(None).compose(chain)
    assert [b.stage.value for b in body.beats] == ["initial_access", "lateral_movement"]
    assert body.beats[0].detection_count == 1
    assert body.beats[0].technique_ids == ["T1110"]


async def test_template_mode_when_no_llm_is_configured() -> None:
    body = await _composer(None).compose(_chain())
    assert body.degraded is True
    assert body.degraded_reason == "llm_disabled"
    assert "initial_access" in body.summary
    assert body.model.from_live_provider is False


async def test_a_grounded_summary_is_kept() -> None:
    client = canned_client(
        "The attacker gained a foothold [initial_access], then moved laterally [lateral_movement]."
    )
    body = await _composer(client).compose(_chain())
    assert body.degraded is False
    assert set(body.cited_refs) == {"initial_access", "lateral_movement"}


async def test_an_ungrounded_summary_falls_back_to_the_template() -> None:
    client = canned_client("Something bad happened.")
    body = await _composer(client).compose(_chain())
    assert body.degraded is True
    assert body.degraded_reason == "ungrounded_output"


async def test_a_summary_citing_an_unknown_stage_falls_back() -> None:
    client = canned_client("This chain involved [exfiltration] which never happened here.")
    body = await _composer(client).compose(_chain())
    assert body.degraded is True
    assert body.degraded_reason == "ungrounded_output"


async def test_a_provider_outage_degrades_to_the_template() -> None:
    client = build_client(scripted_provider_raising(ProviderUnavailable("down")))
    body = await _composer(client).compose(_chain())
    assert body.degraded is True
    assert body.degraded_reason == "llm_error:ProviderUnavailable"


async def test_a_chain_with_no_stages_never_calls_the_llm() -> None:
    calls: list[int] = []

    def handler(_req: Any) -> Any:
        calls.append(1)
        from sm_ai import LlmResponse

        return LlmResponse(text="should never run")

    client = build_client(DeterministicAdapter(handler))  # type: ignore[arg-type]
    body = await _composer(client).compose(_chain(stages=[]))
    assert calls == []
    assert body.degraded is True
    assert body.degraded_reason == "no_stages"
    assert body.beats == []


async def test_a_synthetic_subject_id_narrates_as_synthetic_tier() -> None:
    body = await _composer(None).compose(_chain(subject_id="sim-host-01"))
    assert body.simulated is True
    assert all(b.tier == GroundingKind.synthetic for b in body.beats)


async def test_a_real_subject_id_narrates_as_evidence_tier() -> None:
    body = await _composer(None).compose(_chain(subject_id="web01"))
    assert body.simulated is False
    assert all(b.tier == GroundingKind.evidence for b in body.beats)
