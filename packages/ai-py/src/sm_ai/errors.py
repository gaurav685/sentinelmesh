"""Typed failures for the AI layer.

Every one is catchable as `AiError`. The AI analyst / agents translate these to
a deterministic fallback or a surfaced error — never a crash, never a silent
degrade without an observable signal.
"""

from __future__ import annotations

__all__ = [
    "AiError",
    "ContextPoisoningDetected",
    "OutputValidationError",
    "PromptInjectionDetected",
    "ProviderRefused",
    "ProviderTimeout",
    "ProviderUnavailable",
    "TokenBudgetExceeded",
    "ToolAuthorizationError",
    "ToolInputInvalid",
    "ToolOutputInvalid",
    "UnknownToolError",
]


class AiError(Exception):
    """Base for every AI-layer failure."""


# ---- provider boundary --------------------------------------------
class ProviderUnavailable(AiError):
    """The configured provider cannot be reached or is not configured (e.g. no
    API key). The caller degrades to a deterministic path."""


class ProviderTimeout(AiError):
    """The provider did not answer within the deadline."""


class ProviderRefused(AiError):
    """The provider returned a content-policy refusal or a non-retryable 4xx.
    Never retried."""


# ---- budgets / limits -------------------------------------------
class TokenBudgetExceeded(AiError):
    """A request's estimated prompt tokens, or a run's cumulative tokens, exceed
    the configured ceiling. Raised before any network I/O for the per-call case."""


# ---- trust boundary --------------------------------------------
class PromptInjectionDetected(AiError):
    """Retrieved/telemetry content contains an instruction-injection pattern.
    The content is still usable as *data*; this flags it for the caller."""


class ContextPoisoningDetected(AiError):
    """Assembled context exceeds a sanity bound or contains a disallowed
    construct (e.g. a fake system turn embedded in evidence text)."""


class OutputValidationError(AiError):
    """The model's output does not satisfy the required schema / grounding
    contract after the allowed repair attempts."""


# ---- tools ----------------------------------------------------
class UnknownToolError(AiError):
    """The model asked for a tool that is not in the registry."""


class ToolAuthorizationError(AiError):
    """The caller's principal lacks the permission the tool requires. The LLM
    asking for it changes nothing."""


class ToolInputInvalid(AiError):
    """Tool arguments failed schema validation."""


class ToolOutputInvalid(AiError):
    """A tool produced output that failed its own output schema — a bug in the
    tool, surfaced rather than passed to the model."""
