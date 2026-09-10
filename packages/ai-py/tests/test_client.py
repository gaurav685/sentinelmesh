from __future__ import annotations

import asyncio

import pytest

from sm_ai.client import AuditEvent, LlmClient
from sm_ai.errors import (
    ProviderRefused,
    ProviderTimeout,
    ProviderUnavailable,
    TokenBudgetExceeded,
)
from sm_ai.tokens import RunBudget

from .conftest import ScriptedProvider, make_request


def _client(provider: ScriptedProvider, **kw: object) -> tuple[LlmClient, list[AuditEvent]]:
    events: list[AuditEvent] = []
    defaults = {
        "provider": provider,
        "max_prompt_tokens": 10_000,
        "timeout_s": 0.5,
        "max_retries": 2,
        "retry_backoff_s": 0.0,
        "audit_sink": events.append,
    }
    defaults.update(kw)
    return LlmClient(**defaults), events  # type: ignore[arg-type]


async def test_happy_path_returns_and_audits_ok() -> None:
    client, events = _client(ScriptedProvider(["the answer"]))
    resp = await client.complete(make_request("question", purpose="triage"))
    assert resp.text == "the answer"
    assert [e.outcome for e in events] == ["ok"]
    assert events[0].purpose == "triage"
    assert events[0].prompt_sha256 and "question" not in events[0].prompt_sha256


async def test_per_call_prompt_ceiling_trips_before_any_provider_call() -> None:
    provider = ScriptedProvider(["never reached"])
    client, events = _client(provider, max_prompt_tokens=2)
    with pytest.raises(TokenBudgetExceeded):
        await client.complete(make_request("a fairly long prompt that will not fit"))
    assert provider.calls == []
    assert events[-1].outcome == "budget"


async def test_run_budget_stops_the_call() -> None:
    provider = ScriptedProvider(["x"])
    client, events = _client(provider)
    budget = RunBudget(max_total_tokens=5)  # smaller than the prompt estimate
    with pytest.raises(TokenBudgetExceeded):
        await client.complete(make_request("hello there analyst"), run_budget=budget)
    assert provider.calls == []
    assert events[-1].outcome == "budget"


async def test_transient_failure_is_retried_then_succeeds() -> None:
    provider = ScriptedProvider([ProviderUnavailable("boom"), "recovered"])
    client, events = _client(provider)
    resp = await client.complete(make_request("q"))
    assert resp.text == "recovered"
    assert [e.outcome for e in events] == ["unavailable", "ok"]
    assert len(provider.calls) == 2


async def test_a_policy_refusal_is_not_retried() -> None:
    provider = ScriptedProvider([ProviderRefused("policy"), "would recover"])
    client, events = _client(provider)
    with pytest.raises(ProviderRefused):
        await client.complete(make_request("q"))
    assert len(provider.calls) == 1
    assert [e.outcome for e in events] == ["refused"]


async def test_persistent_transient_failure_exhausts_retries_and_raises() -> None:
    provider = ScriptedProvider([ProviderUnavailable("down")])
    client, events = _client(provider, max_retries=2)
    with pytest.raises(ProviderUnavailable):
        await client.complete(make_request("q"))
    assert len(provider.calls) == 3  # 1 + 2 retries
    assert [e.outcome for e in events] == ["unavailable", "unavailable", "unavailable"]


async def test_a_slow_provider_times_out() -> None:
    provider = ScriptedProvider(["too late"], sleep_s=5.0)
    client, events = _client(provider, timeout_s=0.05, max_retries=0)
    with pytest.raises(ProviderTimeout):
        await client.complete(make_request("q"))
    assert events[-1].outcome == "timeout"


async def test_cancellation_before_the_call_is_honoured() -> None:
    provider = ScriptedProvider(["unused"])
    client, _ = _client(provider)
    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(ProviderUnavailable, match="cancelled"):
        await client.complete(make_request("q"), cancel=cancel)
    assert provider.calls == []


async def test_audit_sink_may_be_async() -> None:
    seen: list[str] = []

    async def sink(e: AuditEvent) -> None:
        seen.append(e.outcome)

    client, _ = _client(ScriptedProvider(["ok"]), audit_sink=sink)
    await client.complete(make_request("q"))
    assert seen == ["ok"]
