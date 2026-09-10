"""The provider boundary.

An `LlmProvider` turns an `LlmRequest` into an `LlmResponse` or raises a typed
`Provider*` error. It does nothing else — no retries, no budgeting, no auditing
(that is `LlmClient`'s job). Adapters live in `sm_ai.adapters`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .messages import LlmRequest, LlmResponse

__all__ = ["LlmProvider", "ProviderInfo"]


class ProviderInfo:
    __slots__ = ("is_live", "name", "supports_tools")

    def __init__(self, name: str, *, supports_tools: bool, is_live: bool) -> None:
        self.name = name
        #: True when a tool-calling API is available.
        self.supports_tools = supports_tools
        #: True only for an adapter that actually reaches a remote provider. A
        #: `False` here means no output from this provider may be described as
        #: "verified against a live LLM".
        self.is_live = is_live


@runtime_checkable
class LlmProvider(Protocol):
    @property
    def info(self) -> ProviderInfo: ...

    async def complete(self, request: LlmRequest, *, timeout_s: float) -> LlmResponse:
        """Return the model's answer, or raise `ProviderUnavailable` /
        `ProviderTimeout` / `ProviderRefused`."""
        ...
