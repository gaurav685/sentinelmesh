"""Provider adapters.

- `DeterministicAdapter` — no network, fully reproducible. The default when no
  credentials are configured, and what every test uses.
- `HttpLlmBoundary` — the real boundary for an Anthropic-/OpenAI-compatible
  Messages API. Inert (raises `ProviderUnavailable`) with no API key, and never
  claimed as verified — no credentials are available in this project.
"""

from __future__ import annotations

from .deterministic import DeterministicAdapter, ScriptedReply
from .http import HttpLlmBoundary

__all__ = ["DeterministicAdapter", "HttpLlmBoundary", "ScriptedReply"]
