"""`LlmClient` — the only thing the AI analyst and the agents call.

It wraps a provider with the cross-cutting concerns that must never be skipped:

- a hard per-call prompt-token ceiling, checked *before* any network I/O;
- an optional per-run cumulative token budget (`RunBudget`);
- a wall-clock timeout and cooperative cancellation;
- a bounded retry on transient provider failures only;
- an audit record for every attempt (prompt hash, purpose, usage, outcome) via
  a caller-supplied sink — the raw prompt is never logged by default.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .errors import ProviderRefused, ProviderTimeout, ProviderUnavailable, TokenBudgetExceeded
from .messages import LlmRequest, LlmResponse
from .provider import LlmProvider
from .tokens import RunBudget, estimate_message_tokens

__all__ = ["AuditEvent", "LlmClient"]

AuditSink = Callable[["AuditEvent"], Awaitable[None]] | Callable[["AuditEvent"], None]


@dataclass(frozen=True)
class AuditEvent:
    purpose: str
    provider: str
    model: str
    prompt_sha256: str
    prompt_tokens_estimated: int
    attempt: int
    outcome: str  # "ok" | "timeout" | "unavailable" | "refused" | "budget"
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    from_live_provider: bool = False
    detail: str = ""


@dataclass
class LlmClient:
    provider: LlmProvider
    max_prompt_tokens: int
    timeout_s: float
    max_retries: int = 2
    retry_backoff_s: float = 0.2
    audit_sink: AuditSink | None = None
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    async def _emit(self, event: AuditEvent) -> None:
        if self.audit_sink is None:
            return
        result = self.audit_sink(event)
        if asyncio.iscoroutine(result):
            await result

    async def complete(
        self,
        request: LlmRequest,
        *,
        run_budget: RunBudget | None = None,
        cancel: asyncio.Event | None = None,
    ) -> LlmResponse:
        prompt_tokens_est = estimate_message_tokens(request.messages)
        prompt_sha = hashlib.sha256(
            "\n".join(f"{m.role}:{m.content}" for m in request.messages).encode()
        ).hexdigest()

        def _audit(attempt: int, outcome: str, latency_ms: int, **kw: object) -> AuditEvent:
            return AuditEvent(
                purpose=request.purpose,
                provider=self.provider.info.name,
                model=request.model,
                prompt_sha256=prompt_sha,
                prompt_tokens_estimated=prompt_tokens_est,
                attempt=attempt,
                outcome=outcome,
                latency_ms=latency_ms,
                **kw,  # type: ignore[arg-type]
            )

        # Budget checks happen before any network I/O.
        if prompt_tokens_est > self.max_prompt_tokens:
            await self._emit(_audit(0, "budget", 0, detail="per-call prompt ceiling"))
            raise TokenBudgetExceeded(
                f"prompt is ~{prompt_tokens_est} tokens, ceiling is {self.max_prompt_tokens}"
            )
        if run_budget is not None:
            try:
                run_budget.check(prompt_tokens_est)
            except TokenBudgetExceeded:
                await self._emit(_audit(0, "budget", 0, detail="run budget"))
                raise

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            if cancel is not None and cancel.is_set():
                raise ProviderUnavailable("cancelled before LLM call")
            started = self._clock()
            try:
                resp = await asyncio.wait_for(
                    self.provider.complete(request, timeout_s=self.timeout_s),
                    timeout=self.timeout_s + 1.0,
                )
            except (TimeoutError, ProviderTimeout) as exc:
                last_exc = ProviderTimeout(str(exc) or "llm call timed out")
                await self._emit(
                    _audit(attempt, "timeout", int((self._clock() - started) * 1000))
                )
            except ProviderUnavailable as exc:
                last_exc = exc
                await self._emit(
                    _audit(attempt, "unavailable", int((self._clock() - started) * 1000),
                           detail=str(exc)[:200])
                )
            except ProviderRefused as exc:
                # A policy refusal is never retried.
                await self._emit(
                    _audit(attempt, "refused", int((self._clock() - started) * 1000),
                           detail=str(exc)[:200])
                )
                raise
            else:
                latency_ms = int((self._clock() - started) * 1000)
                if run_budget is not None:
                    run_budget.charge(resp.usage)
                await self._emit(
                    _audit(
                        attempt, "ok", latency_ms,
                        prompt_tokens=resp.usage.prompt_tokens,
                        completion_tokens=resp.usage.completion_tokens,
                        from_live_provider=resp.from_live_provider,
                    )
                )
                return resp

            if attempt <= self.max_retries:
                await asyncio.sleep(self.retry_backoff_s * attempt)

        assert last_exc is not None
        raise last_exc
