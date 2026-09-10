"""The wire types for a single LLM call.

Provider-neutral. An adapter maps these to/from its own API shape. Nothing here
executes anything — a `ToolCall` in a response is a *request* from the model that
the caller decides whether to honour.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from sm_contracts import SmBaseModel

__all__ = [
    "FinishReason",
    "LlmMessage",
    "LlmRequest",
    "LlmResponse",
    "MessageRole",
    "TokenUsage",
    "ToolCall",
    "ToolSpec",
]


class MessageRole(StrEnum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class FinishReason(StrEnum):
    stop = "stop"
    length = "length"
    tool_call = "tool_call"
    content_filter = "content_filter"
    error = "error"


class ToolSpec(SmBaseModel):
    """A tool offered to the model: name + JSON-Schema for its arguments.

    This is the *only* description the model gets. It carries no capability — the
    registry decides authorization and validation independently.
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    description: str = Field(min_length=1, max_length=2_000)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCall(SmBaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class LlmMessage(SmBaseModel):
    role: MessageRole
    content: str = Field(max_length=800_000)
    # Set on a `tool` message: which tool call this is the result of.
    tool_call_id: str | None = Field(default=None, max_length=128)
    # Set on an `assistant` message that requested tools (echoed back on the
    # next turn so the provider can thread the conversation).
    tool_calls: tuple[ToolCall, ...] = ()


class TokenUsage(SmBaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


class LlmRequest(SmBaseModel):
    model: str = Field(min_length=1, max_length=128)
    messages: tuple[LlmMessage, ...] = Field(min_length=1)
    max_completion_tokens: int = Field(default=1_024, ge=1, le=32_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    tools: tuple[ToolSpec, ...] = ()
    # An opaque tag threaded into the audit record — never sent to the provider.
    purpose: str = Field(default="", max_length=64)


class LlmResponse(SmBaseModel):
    text: str = Field(default="", max_length=800_000)
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: FinishReason = FinishReason.stop
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str = Field(default="", max_length=128)
    provider: str = Field(default="", max_length=32)
    # True only when an adapter actually reached a remote provider. The
    # deterministic adapter leaves it False — nothing in the platform may claim
    # "verified against a live provider" off a False here.
    from_live_provider: bool = False
