from __future__ import annotations

from sm_ai import DeterministicAdapter
from sm_ai.errors import ProviderUnavailable
from sm_ai_analyst.analyst import IncidentAnalyst
from sm_contracts import EvidenceRef, ExplainRequest

from .conftest import build_client, canned_client, make_request, scripted_provider_raising


def _analyst(client: object | None) -> IncidentAnalyst:
    return IncidentAnalyst(client, model="test-model", max_output_tokens=500)  # type: ignore[arg-type]


async def test_template_mode_when_no_llm_is_configured() -> None:
    result = await _analyst(None).explain(make_request())
    assert result.degraded is True
    assert result.degraded_reason == "llm_disabled"
    assert "12 failed logins" in result.summary
    assert set(result.cited_refs) == {"det-1", "T1110"}
    assert result.recommendations  # a fixed vetted list, not model-authored
    assert result.model.from_live_provider is False


async def test_a_grounded_answer_is_kept() -> None:
    client = canned_client("The host had 12 failed logins [det-1], consistent with brute force [T1110].")
    result = await _analyst(client).explain(make_request())
    assert result.degraded is False
    assert result.cited_refs == ["T1110", "det-1"]
    # DeterministicAdapter is not a live provider, so confidence stays low.
    assert result.confidence == "low"


async def test_an_answer_with_no_citation_falls_back_to_the_template() -> None:
    client = canned_client("Something suspicious happened on the host.")
    result = await _analyst(client).explain(make_request())
    assert result.degraded is True
    assert result.degraded_reason == "ungrounded_output"


async def test_an_answer_citing_an_unknown_ref_falls_back() -> None:
    client = canned_client("See the correlated finding [det-999].")
    result = await _analyst(client).explain(make_request())
    assert result.degraded is True
    assert result.degraded_reason == "ungrounded_output"


async def test_injection_in_evidence_is_flagged_but_still_answered() -> None:
    client = canned_client("Repeated failed logins [det-1] map to brute force [T1110].")
    result = await _analyst(client).explain(make_request(with_injection=True))
    assert result.evidence_flagged is True
    assert result.degraded is False  # the content was fenced, not obeyed


async def test_a_provider_outage_degrades_to_the_template() -> None:
    client = build_client(scripted_provider_raising(ProviderUnavailable("down")))
    result = await _analyst(client).explain(make_request())
    assert result.degraded is True
    assert result.degraded_reason == "llm_error:ProviderUnavailable"


async def test_oversized_evidence_is_rejected_and_the_trusted_subset_is_kept() -> None:
    big = EvidenceRef(
        kind="event", ref="evt-big", provenance="svc:1", content="x " * 8_000
    )
    small = EvidenceRef(
        kind="technique", ref="T1110", provenance="mitre-service:catalog",
        content="Brute Force", trusted=True,
    )
    req = ExplainRequest(
        subject_type="detection", subject_id="d", task="summarize", evidence=[big, small]
    )
    result = await IncidentAnalyst(
        None, model="m", max_output_tokens=100, max_context_chars=1_000
    ).explain(req)
    assert result.degraded is True
    assert result.degraded_reason == "context_rejected"
    assert result.cited_refs == ["T1110"]


async def test_the_repair_turn_is_offered_once_then_it_gives_up() -> None:
    calls: list[int] = []

    def handler(_req: object) -> object:
        calls.append(1)
        from sm_ai import LlmResponse

        return LlmResponse(text="no citations here")

    client = build_client(DeterministicAdapter(handler))  # type: ignore[arg-type]
    result = await _analyst(client).explain(make_request())
    assert len(calls) == 2  # first attempt + one repair
    assert result.degraded is True
