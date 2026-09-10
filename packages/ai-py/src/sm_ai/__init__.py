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
from .agents import (
    DETECTION_AGENT,
    RESPONSE_AGENT,
    THREAT_INTEL_AGENT,
    AgentLimits,
    AgentReport,
    AgentSpec,
    Finding,
    ProposedAction,
    action_gate,
    run_agent,
)
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
from .evidence import EvidenceBuilder, EvidenceBundle, EvidenceItem
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
from .prompt import ANALYST_SYSTEM_RULES, build_grounded_messages
from .provider import LlmProvider, ProviderInfo
from .registry import ToolInvocationRecord, ToolRegistry
from .sanitize import fence_untrusted, scan_for_injection
from .tokens import RunBudget, estimate_message_tokens, estimate_tokens
from .tools import FunctionTool, Tool, ToolContext, ToolOutcome, ToolPrincipal

__all__ = [
    "ANALYST_SYSTEM_RULES",
    "DETECTION_AGENT",
    "RESPONSE_AGENT",
    "THREAT_INTEL_AGENT",
    "AgentLimits",
    "AgentReport",
    "AgentSpec",
    "AiError",
    "AuditEvent",
    "ContextPoisoningDetected",
    "DeterministicAdapter",
    "EvidenceBuilder",
    "EvidenceBundle",
    "EvidenceItem",
    "Finding",
    "FinishReason",
    "FunctionTool",
    "HttpLlmBoundary",
    "LlmClient",
    "LlmMessage",
    "LlmProvider",
    "LlmRequest",
    "LlmResponse",
    "MessageRole",
    "OutputValidationError",
    "PromptInjectionDetected",
    "ProposedAction",
    "ProviderInfo",
    "ProviderRefused",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RunBudget",
    "ScriptedReply",
    "TokenBudgetExceeded",
    "TokenUsage",
    "Tool",
    "ToolAuthorizationError",
    "ToolCall",
    "ToolContext",
    "ToolInputInvalid",
    "ToolInvocationRecord",
    "ToolOutcome",
    "ToolOutputInvalid",
    "ToolPrincipal",
    "ToolRegistry",
    "ToolSpec",
    "UnknownToolError",
    "action_gate",
    "build_grounded_messages",
    "estimate_message_tokens",
    "estimate_tokens",
    "fence_untrusted",
    "run_agent",
    "scan_for_injection",
]
