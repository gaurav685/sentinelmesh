from __future__ import annotations

import httpx
import pytest
import respx
from sm_ai.adapters import DeterministicAdapter, HttpLlmBoundary, ScriptedReply
from sm_ai.errors import ProviderRefused, ProviderUnavailable
from sm_ai.messages import FinishReason, LlmResponse

from .conftest import make_request


async def test_deterministic_adapter_is_reproducible() -> None:
    adapter = DeterministicAdapter.canned("fixed answer")
    req = make_request("summarise this incident")
    a = await adapter.complete(req, timeout_s=5)
    b = await adapter.complete(req, timeout_s=5)
    assert a == b
    assert a.text == "fixed answer"
    assert a.provider == "deterministic"
    assert a.from_live_provider is False
    assert a.usage.prompt_tokens > 0 and a.usage.completion_tokens > 0


async def test_deterministic_adapter_scripted_matches_first_rule() -> None:
    adapter = DeterministicAdapter.scripted(
        [
            ScriptedReply(
                when=lambda r: "triage" in r.messages[-1].content,
                then=LlmResponse(text="triage: medium"),
            ),
            ScriptedReply(
                when=lambda r: True,
                then=LlmResponse(text="default"),
            ),
        ]
    )
    assert (await adapter.complete(make_request("please triage"), timeout_s=5)).text == "triage: medium"
    assert (await adapter.complete(make_request("hello"), timeout_s=5)).text == "default"


async def test_deterministic_adapter_echo() -> None:
    adapter = DeterministicAdapter.echo()
    out = await adapter.complete(make_request("system A", "user B"), timeout_s=5)
    assert out.text == "echo: user B"


async def test_http_boundary_is_inert_without_a_key() -> None:
    boundary = HttpLlmBoundary(api_key=None)
    assert boundary.info.is_live is False
    with pytest.raises(ProviderUnavailable, match="no API key"):
        await boundary.complete(make_request("hi"), timeout_s=5)


async def test_http_boundary_reports_live_only_when_a_key_is_present() -> None:
    assert HttpLlmBoundary(api_key="sk-test").info.is_live is True


@respx.mock
async def test_http_boundary_maps_a_messages_response() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "claude-x",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "hello from the model"}],
                "usage": {"input_tokens": 12, "output_tokens": 3},
            },
        )
    )
    async with httpx.AsyncClient() as client:
        boundary = HttpLlmBoundary(api_key="sk-test", http=client)
        out = await boundary.complete(make_request("hi"), timeout_s=5)
    assert out.text == "hello from the model"
    assert out.finish_reason is FinishReason.stop
    assert out.from_live_provider is True
    assert out.usage.prompt_tokens == 12


@respx.mock
async def test_http_boundary_4xx_is_refused_5xx_is_unavailable() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages")
    async with httpx.AsyncClient() as client:
        boundary = HttpLlmBoundary(api_key="sk-test", http=client)
        route.mock(return_value=httpx.Response(400, json={}))
        with pytest.raises(ProviderRefused):
            await boundary.complete(make_request("hi"), timeout_s=5)
        route.mock(return_value=httpx.Response(503, json={}))
        with pytest.raises(ProviderUnavailable):
            await boundary.complete(make_request("hi"), timeout_s=5)
