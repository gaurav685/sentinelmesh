"""Attack storytelling (Phase 14; req 33): a cinematic breach replay for
one attack chain.

Every beat's factual fields (`stage`, `detection_ids`, `technique_ids`,
timestamps) come straight from `correlation-engine`'s own
`ChainStageModel` — never touched by the LLM, never fabricated.
`summary` is the one LLM-composed part, grounded with the exact same
citation-and-retry mechanism `IncidentAnalyst.explain` uses: every
sentence must cite a beat's `stage` value, one retry on an ungrounded
answer, then a deterministic factual template (`degraded=True`) — the
model never gets a third try to invent a stage that isn't in the chain.

A chain whose subject is a simulation-generated id
(`sm_ml.scenario.is_synthetic_id`) narrates as `GroundingKind.synthetic`
throughout, factual beats included — the narrative never claims a
simulated chain is real.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from sm_ai import (
    AiError,
    EvidenceBuilder,
    EvidenceBundle,
    LlmClient,
    LlmMessage,
    LlmRequest,
    MessageRole,
    build_grounded_messages,
)
from sm_contracts import AnalystModelInfo, AttackChainModel, GroundingKind, NarrativeBeat
from sm_ml.scenario import is_synthetic_id

__all__ = ["NarrativeBody", "NarrativeComposer"]

_CITE = re.compile(r"\[([A-Za-z0-9:_.\-]{1,96})\]")

_TASK_PROMPT = (
    "Narrate this attack chain as a short breach walkthrough, in stage order, "
    "3-8 sentences. Cite the stage each sentence describes, e.g. [initial_access]. "
    "Facts only -- do not invent a stage, a technique, or a detail not in the evidence."
)


class NarrativeBody:
    """The mutable content `NarrativeComposer` assembles — everything
    `sm_contracts.api.narrative.Narrative` carries except identity/subject
    columns, which the repository owns."""

    def __init__(self) -> None:
        self.beats: list[NarrativeBeat] = []
        self.summary: str = ""
        self.cited_refs: list[str] = []
        self.confidence: Literal["low", "medium", "high"] = "low"
        self.model: AnalystModelInfo = AnalystModelInfo()
        self.degraded: bool = False
        self.degraded_reason: str = ""
        self.simulated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "beats": [b.model_dump(mode="json") for b in self.beats],
            "summary": self.summary,
            "cited_refs": self.cited_refs,
            "confidence": self.confidence,
            "model": self.model.model_dump(mode="json"),
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "simulated": self.simulated,
        }


class NarrativeComposer:
    def __init__(
        self, llm: LlmClient | None, *, model: str, max_output_tokens: int,
        max_context_chars: int = 20_000,
        audit: Callable[[str], Awaitable[None]] | Callable[[str], None] | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._max_out = max_output_tokens
        self._max_context = max_context_chars
        self._audit = audit

    @staticmethod
    def beats(chain: AttackChainModel, *, tier: GroundingKind) -> list[NarrativeBeat]:
        """Deterministic — one beat per stage, straight from the chain's
        own data. Never touched by the LLM."""
        return [
            NarrativeBeat(
                at=stage.first_seen, stage=stage.stage,
                title=stage.stage.value.replace("_", " ").title(),
                detection_ids=[str(d) for d in stage.detection_ids],
                technique_ids=list(stage.technique_ids),
                detection_count=stage.detection_count,
                tier=tier,
            )
            for stage in chain.stages
        ]

    async def compose(self, chain: AttackChainModel) -> NarrativeBody:
        tier = GroundingKind.synthetic if is_synthetic_id(chain.subject_id) else GroundingKind.evidence
        body = NarrativeBody()
        body.beats = self.beats(chain, tier=tier)
        body.simulated = tier == GroundingKind.synthetic

        builder = EvidenceBuilder(max_total_chars=self._max_context)
        for beat in body.beats:
            builder.add(
                "stage", beat.stage.value, f"correlation-engine:{chain.id}",
                f"{beat.detection_count} detection(s); technique(s): "
                f"{', '.join(beat.technique_ids) or 'none'}.",
                trusted=True,
            )
        bundle = builder.build()
        valid_refs = set(bundle.refs())

        if not body.beats:
            body.summary = "No kill-chain stages are recorded for this chain yet."
            body.degraded = True
            body.degraded_reason = "no_stages"
            return body

        if self._llm is None:
            self._apply_template(body, bundle, "llm_disabled")
            return body

        messages = list(build_grounded_messages(_TASK_PROMPT, bundle))
        for attempt in (1, 2):
            try:
                resp = await self._llm.complete(
                    LlmRequest(
                        model=self._model, messages=tuple(messages),
                        max_completion_tokens=self._max_out, purpose="analyst.narrate",
                    )
                )
            except AiError as exc:
                await self._emit(f"llm_error:{type(exc).__name__}")
                self._apply_template(body, bundle, f"llm_error:{type(exc).__name__}")
                return body

            cited = _CITE.findall(resp.text)
            grounded = bool(cited) and set(cited) <= valid_refs
            if grounded:
                body.summary = resp.text.strip()
                body.cited_refs = sorted(set(cited))
                body.confidence = self._confidence(resp.from_live_provider, len(set(cited)))
                body.model = AnalystModelInfo(
                    provider=resp.provider, model_id=resp.model, prompt_sha256="",
                    from_live_provider=resp.from_live_provider,
                )
                body.degraded = False
                return body

            if attempt == 1:
                messages.append(LlmMessage(
                    role=MessageRole.user,
                    content=(
                        "Your answer cited an unknown stage or had no citation. Rewrite it "
                        "using ONLY these stage refs, and cite one in every sentence: "
                        + ", ".join(f"[{r}]" for r in sorted(valid_refs))
                    ),
                ))

        await self._emit("ungrounded_output")
        self._apply_template(body, bundle, "ungrounded_output")
        return body

    # ---- helpers -------------------------------------------------
    @staticmethod
    def _confidence(live: bool, n_cites: int) -> Literal["low", "medium", "high"]:
        if not live:
            return "low"
        return "high" if n_cites >= 2 else "medium"

    @staticmethod
    def _apply_template(body: NarrativeBody, bundle: EvidenceBundle, reason: str) -> None:
        lines = ["LLM narration is unavailable — this is a factual walkthrough of the recorded stages."]
        for item in bundle.items:
            lines.append(f"- [{item.ref}] {item.content}")
        body.summary = "\n".join(lines)
        body.cited_refs = [i.ref for i in bundle.items]
        body.confidence = "low"
        body.model = AnalystModelInfo()
        body.degraded = True
        body.degraded_reason = reason

    async def _emit(self, event: str) -> None:
        if self._audit is None:
            return
        result = self._audit(event)
        if asyncio.iscoroutine(result):
            await result
