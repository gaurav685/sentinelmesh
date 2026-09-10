"""SentinelMesh AI layer — the untrusted-LLM boundary.

The LLM is treated as an untrusted, possibly-adversarial component. This package
gives the AI analyst and the defense agents:

- a provider-neutral message/response contract (`sm_ai.messages`);
- a provider boundary (`sm_ai.provider`) with a network-free `DeterministicAdapter`
  and a real `HttpLlmBoundary` that is inert without credentials;
- `LlmClient` — token ceilings enforced before any network call, a per-run
  budget, timeout, cancellation, transient-only retry, and an audit record for
  every attempt.

Later units add the authorized tool registry, the evidence/context builder, and
the agent orchestrator. Nothing here lets an LLM acquire a capability its caller
did not already hold.
"""

from __future__ import annotations

from .adapters import DeterministicAdapter, HttpLlmBoundary, ScriptedReply
from .client import AuditEvent, LlmClient
from .errors import (
    AiError,
    ContextPoisoningDetected,
    OutputValidationError,
    PromptInjectionDetected,
    ProviderRefused,
    ProviderTimeout,
    ProviderUnavailable,
    TokenBudgetExceeded,
    ToolAuthorizationError,
    ToolInputInvalid,
    ToolOutputInvalid,
    UnknownToolError,
)
from .messages import (
    FinishReason,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    MessageRole,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from .provider import LlmProvider, ProviderInfo
from .tokens import RunBudget, estimate_message_tokens, estimate_tokens

__all__ = [
    "AiError",
    "AuditEvent",
    "ContextPoisoningDetected",
    "DeterministicAdapter",
    "FinishReason",
    "HttpLlmBoundary",
    "LlmClient",
    "LlmMessage",
    "LlmProvider",
    "LlmRequest",
    "LlmResponse",
    "MessageRole",
    "OutputValidationError",
    "PromptInjectionDetected",
    "ProviderInfo",
    "ProviderRefused",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RunBudget",
    "ScriptedReply",
    "TokenBudgetExceeded",
    "TokenUsage",
    "ToolAuthorizationError",
    "ToolCall",
    "ToolInputInvalid",
    "ToolOutputInvalid",
    "ToolSpec",
    "UnknownToolError",
    "estimate_message_tokens",
    "estimate_tokens",
]
