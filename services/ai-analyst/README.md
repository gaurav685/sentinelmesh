# ai-analyst

Grounded incident analyst (requirements 14 / 29). HTTP-only, port 8010.

## What it does

`api-gateway` gathers the evidence for a subject (a detection, an attack chain,
an incident) — tenant-scoped, read-only — and calls
`POST /api/v1/analyst/explain` with it. This service:

1. assembles the evidence into a bundle, **fencing every telemetry- or
   third-party-derived item as data** and scanning it for prompt-injection;
2. builds a prompt where the evidence is only ever a `user` turn and the
   `system` turn tells the model the fenced content is inert and that it cannot
   take actions;
3. runs the LLM through `sm_ai.LlmClient` (per-call token ceiling, timeout,
   cancellation, transient-only retry, per-attempt audit);
4. validates grounding — every `[ref]` the summary cites must be a real evidence
   ref; one repair attempt, then it falls back;
5. returns an `Explanation` (`sm_contracts`): `summary`, `cited_refs`,
   `confidence`, a fixed vetted `recommendations` list (never model-authored),
   `model` info, `generated_at`.

## Degraded behaviour

No LLM API key configured (the default — no credentials exist in this project),
a provider outage, a timeout, or output that fails grounding validation → the
analyst returns a **deterministic factual template** of the evidence with
`degraded = true` and a `degraded_reason`. It never invents a narrative and
never claims a live-provider result it did not get.

## Trust boundary

- The analyst holds **no tools** and performs **no action**.
- It never reads a datastore — it only sees the evidence `api-gateway` sent.
- The LLM output can only ever become `summary` text; `recommendations` are a
  fixed per-subject list, so an injection cannot turn them into instructions.

## Multi-agent defense (`POST /api/v1/agents/run`)

Runs a named defense agent (`detection-agent` / `threat-intel-agent` /
`response-orchestration-agent`) over supplied evidence. The agent has a **tool
allow-list** and one registered tool (`search_evidence`, which searches the
provided bundle and needs no permission); any other tool it asks for is refused.
`run_agent` bounds it with `SM_AGENT_MAX_STEPS` / `SM_AGENT_MAX_TOOL_CALLS` /
`SM_AGENT_WALL_CLOCK_TIMEOUT_S` / `SM_AGENT_MAX_LLM_TOKENS_PER_RUN`. An agent
**cannot spawn another agent** and **cannot execute** anything. The response
agent emits proposals; `sm_ai.action_gate` decides — never `allowed` under the
shipped `SM_RESPONSE_MODE=suggest_only`. No LLM key → `status="failed"`.

## Config

`SM_LLM_DEFAULT_PROVIDER`, `SM_LLM_DEFAULT_MODEL`, `SM_LLM_API_KEY`,
`SM_LLM_BASE_URL`, `SM_LLM_MAX_PROMPT_TOKENS`, `SM_LLM_MAX_OUTPUT_TOKENS`,
`SM_LLM_MAX_RETRIES`, `SM_LLM_REQUEST_TIMEOUT_S`.

## Not verified

No live LLM provider has been called from this service. `HttpLlmBoundary` is
written to the Anthropic Messages API shape but has never executed against a real
endpoint (ADR-014 / no credentials).
