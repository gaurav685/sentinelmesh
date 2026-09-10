# sm-ai

The **untrusted-LLM boundary** for SentinelMesh (Phase 10).

The LLM is treated as an untrusted, possibly-adversarial component. This package
is the only sanctioned path to a model:

- **`sm_ai.messages`** — provider-neutral `LlmRequest` / `LlmResponse` /
  `ToolSpec` / `ToolCall` / `TokenUsage`. `LlmResponse.from_live_provider` is
  `True` only when an adapter actually reached a remote provider.
- **`sm_ai.provider` + `sm_ai.adapters`** — the `LlmProvider` protocol;
  `DeterministicAdapter` (network-free, reproducible, `is_live=False` — the
  default with no credentials and what every test uses); `HttpLlmBoundary`
  (Anthropic Messages API shape — raises `ProviderUnavailable` with no API key
  and has never been executed against a live endpoint).
- **`sm_ai.client.LlmClient`** — enforces a per-call prompt-token ceiling
  *before* any network I/O, an optional per-run `RunBudget`, a wall-clock
  timeout, cooperative cancellation, transient-only bounded retry, and one
  `AuditEvent` per attempt (prompt sha256 + purpose + usage + outcome — never
  the raw prompt).
- **`sm_ai.tools` + `sm_ai.registry`** — `Tool` / `FunctionTool` (explicit
  Pydantic args schema, optional `required_permission`, input + output
  validation); `ToolRegistry` deny-by-default (an unknown or unauthorized tool
  call is rejected regardless of the LLM asking; every invocation audited).
- **`sm_ai.sanitize` + `sm_ai.evidence` + `sm_ai.prompt`** — injection scanning,
  the untrusted-content fence, the `EvidenceBuilder` (fences all
  telemetry-derived content as data, caps context size), and
  `build_grounded_messages` (evidence is only ever a `user` turn).

Nothing here lets an LLM acquire a capability its caller did not already hold.

`sm-ai[gnn]` — n/a. Optional extra `dev` = pytest + respx.
