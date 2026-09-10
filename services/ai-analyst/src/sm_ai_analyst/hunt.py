"""Natural-language -> `QueryPlan` translation, and hunt-result explanation.

The LLM's job is **only** to emit a `QueryPlan` (a closed schema) or say the
request is out of scope. Its output is parsed into the `QueryPlan` Pydantic model
and never used as a query. If it cannot produce a valid plan — or there is no LLM
— the request is `unsupported`, never guessed.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from sm_ai import (
    AiError,
    EvidenceBuilder,
    LlmClient,
    LlmMessage,
    LlmRequest,
    MessageRole,
    build_grounded_messages,
)
from sm_contracts import HuntResult, NlHuntRequest, PlanResponse, QueryPlan

__all__ = ["HuntPlanner", "explain_hunt"]

_INTENTS = (
    "find_entity: locate one entity by type + natural key value\n"
    "list_related: entities related to one entity (optionally filtered by rel_types)\n"
    "path_between: shortest path between two entities (exactly 2 selectors)\n"
    "detections_for: detections involving one entity\n"
    "chains_for: attack chains involving one entity\n"
    "indicator_sightings: hosts/identities/processes an IOC (ip/domain/file) touches\n"
    "technique_usage: subjects mapped to an ATT&CK technique (selector type attack_technique)\n"
)
_ENTITY_TYPES = (
    "identity, host, ip, domain, process, file, detection, attack_chain, "
    "attack_technique, threat_actor, campaign"
)

_SYSTEM = (
    "You translate a SOC analyst's natural-language threat-hunting question into a "
    "structured QueryPlan. You do NOT write Cypher, SQL, or any query language. You "
    "do NOT execute anything.\n\n"
    "Reply with a single JSON object and nothing else. Either:\n"
    '  {"intent": "<one of the intents>", "selectors": [{"type": "<entity type>", '
    '"value": "<the identifier from the question>"}], "rel_types": [], '
    '"limits": {"max_depth": 2, "max_rows": 100}}\n'
    "or, if the question cannot be expressed as one of the intents below:\n"
    '  {"unsupported": true, "reason": "<short reason>"}\n\n'
    f"Intents:\n{_INTENTS}\n"
    f"Entity types: {_ENTITY_TYPES}\n"
    "rel_types is only allowed for list_related and each must be an ATT&CK-style "
    "relationship name. path_between needs exactly two selectors; every other intent "
    "needs exactly one. Never invent an identifier the question does not contain — if "
    "the question is vague, return unsupported."
)

_FEWSHOT = (
    'Q: "show me everything connected to host web01"\n'
    'A: {"intent": "list_related", "selectors": [{"type": "host", "value": "web01"}], '
    '"rel_types": [], "limits": {"max_depth": 2, "max_rows": 100}}\n\n'
    'Q: "which users hit T1110"\n'
    'A: {"intent": "technique_usage", "selectors": [{"type": "attack_technique", '
    '"value": "T1110"}], "rel_types": [], "limits": {"max_depth": 2, "max_rows": 100}}\n\n'
    'Q: "tell me a joke"\n'
    'A: {"unsupported": true, "reason": "not a threat-hunting question"}'
)


class HuntPlanner:
    def __init__(self, llm: LlmClient | None, *, model: str) -> None:
        self._llm = llm
        self._model = model

    async def plan(self, req: NlHuntRequest) -> PlanResponse:
        if self._llm is None:
            return PlanResponse(supported=False, unsupported_reason="llm_unavailable")

        messages = (
            LlmMessage(role=MessageRole.system, content=_SYSTEM + "\n\nExamples:\n" + _FEWSHOT),
            LlmMessage(role=MessageRole.user, content=f"Q: {req.query!r}\nA:"),
        )
        try:
            resp = await self._llm.complete(
                LlmRequest(
                    model=self._model,
                    messages=messages,
                    max_completion_tokens=400,
                    purpose="hunt.plan",
                )
            )
        except AiError as exc:
            return PlanResponse(
                supported=False, unsupported_reason=f"planner error: {type(exc).__name__}"
            )

        obj = _extract_json(resp.text)
        if obj is None:
            return PlanResponse(
                supported=False, unsupported_reason="could not parse a plan from the model"
            )
        if obj.get("unsupported"):
            reason = str(obj.get("reason", "out of scope"))[:300]
            return PlanResponse(supported=False, unsupported_reason=reason)

        try:
            plan = QueryPlan.model_validate(obj)
        except ValidationError:
            return PlanResponse(
                supported=False, unsupported_reason="the model did not produce a valid QueryPlan"
            )
        # The plan's row limit never exceeds what the caller asked for.
        plan = plan.model_copy(
            update={
                "limits": plan.limits.model_copy(
                    update={"max_rows": min(plan.limits.max_rows, req.max_rows)}
                )
            }
        )
        return PlanResponse(supported=True, plan=plan)


def _extract_json(text: str) -> dict[str, object] | None:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def explain_hunt(
    llm: LlmClient | None, model: str, result: HuntResult
) -> str:
    """A grounded one-paragraph summary of a hunt result. Deterministic when
    there is no LLM."""
    sel = ", ".join(f"{s.type}={s.value}" for s in result.plan.selectors)
    baseline = (
        f"Intent '{result.intent}' over {sel}: {result.row_count} result(s)"
        + (" (truncated at the row cap)" if result.truncated else "")
        + "."
    )
    if llm is None or result.row_count == 0:
        return baseline

    rows_text = "\n".join(
        f"- {r.get('labels', r.get('kind', '?'))}: {r.get('properties', {})}"
        for r in result.rows[:25]
    )
    bundle = (
        EvidenceBuilder()
        .add("plan", "plan", "graph-service:hunt", f"intent={result.intent} selectors={sel}", trusted=True)
        .add("rows", "rows", "graph-service:hunt", rows_text)
        .build()
    )
    messages = build_grounded_messages(
        "Summarise this threat-hunt result in 2-3 sentences. Cite [plan] and [rows]. "
        "State only what the rows show; do not speculate about intent.",
        bundle,
    )
    try:
        resp = await llm.complete(
            LlmRequest(model=model, messages=messages, max_completion_tokens=300, purpose="hunt.explain")
        )
    except AiError:
        return baseline
    text = resp.text.strip()
    return text if text else baseline
