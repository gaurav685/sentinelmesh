"""A network-free, fully deterministic provider.

Given the same request it always returns the same response. Construct it with:

- `DeterministicAdapter.canned("text")` — always the same answer;
- `DeterministicAdapter.scripted([...])` — first matching `ScriptedReply` wins,
  with a fallback;
- `DeterministicAdapter(handler)` — an arbitrary pure function of the request.

It is the default provider when no API key is set, and the provider every test
uses. `info.is_live` is always `False`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..messages import FinishReason, LlmRequest, LlmResponse, MessageRole, TokenUsage
from ..provider import ProviderInfo
from ..tokens import estimate_message_tokens, estimate_tokens

__all__ = ["DeterministicAdapter", "ScriptedReply"]

Handler = Callable[[LlmRequest], LlmResponse]


@dataclass(frozen=True)
class ScriptedReply:
    """If `when` returns True for the request, reply with `then`."""

    when: Callable[[LlmRequest], bool]
    then: LlmResponse


class DeterministicAdapter:
    def __init__(self, handler: Handler, *, name: str = "deterministic") -> None:
        self._handler = handler
        self._info = ProviderInfo(name, supports_tools=True, is_live=False)

    @property
    def info(self) -> ProviderInfo:
        return self._info

    async def complete(self, request: LlmRequest, *, timeout_s: float) -> LlmResponse:
        resp = self._handler(request)
        # Fill usage/model/provider deterministically if the handler didn't.
        prompt_tokens = resp.usage.prompt_tokens or estimate_message_tokens(request.messages)
        completion_tokens = resp.usage.completion_tokens or estimate_tokens(resp.text)
        return resp.model_copy(
            update={
                "model": resp.model or request.model,
                "provider": self._info.name,
                "from_live_provider": False,
                "usage": TokenUsage(
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
                ),
            }
        )

    # ---- constructors -------------------------------------------
    @classmethod
    def canned(cls, text: str, *, finish_reason: FinishReason = FinishReason.stop) -> DeterministicAdapter:
        reply = LlmResponse(text=text, finish_reason=finish_reason)
        return cls(lambda _req: reply)

    @classmethod
    def scripted(
        cls, replies: list[ScriptedReply], *, fallback: LlmResponse | None = None
    ) -> DeterministicAdapter:
        default = fallback or LlmResponse(
            text="", finish_reason=FinishReason.error
        )

        def handler(req: LlmRequest) -> LlmResponse:
            for r in replies:
                if r.when(req):
                    return r.then
            return default

        return cls(handler)

    @classmethod
    def echo(cls) -> DeterministicAdapter:
        """Echoes the last user turn — handy for wiring tests."""

        def handler(req: LlmRequest) -> LlmResponse:
            last_user = next(
                (m.content for m in reversed(req.messages) if m.role is MessageRole.user), ""
            )
            return LlmResponse(text=f"echo: {last_user}")

        return cls(handler)
