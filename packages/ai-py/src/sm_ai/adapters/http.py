"""The real provider boundary for an Anthropic Messages-style HTTP API.

**No credentials are available in this project.** With no API key this adapter
raises `ProviderUnavailable` on every call and the AI layer degrades to
deterministic templates. The request/response mapping below is written to the
public API shape but has never been executed against a live endpoint — nothing
in SentinelMesh may claim otherwise (`info.is_live` reflects only whether a key
is present, not whether a call has ever succeeded).
"""

from __future__ import annotations

from typing import Any

import httpx

from ..errors import ProviderRefused, ProviderTimeout, ProviderUnavailable
from ..messages import FinishReason, LlmRequest, LlmResponse, MessageRole, TokenUsage, ToolCall
from ..provider import ProviderInfo

__all__ = ["HttpLlmBoundary"]

_FINISH = {
    "end_turn": FinishReason.stop,
    "max_tokens": FinishReason.length,
    "tool_use": FinishReason.tool_call,
    "stop_sequence": FinishReason.stop,
}


class HttpLlmBoundary:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None = None,
        provider_name: str = "anthropic",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self._http = http
        self._info = ProviderInfo(
            provider_name, supports_tools=True, is_live=bool(api_key)
        )

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def _payload(self, request: LlmRequest) -> dict[str, Any]:
        system = "\n\n".join(
            m.content for m in request.messages if m.role is MessageRole.system
        )
        turns = [
            {"role": m.role.value, "content": m.content}
            for m in request.messages
            if m.role in (MessageRole.user, MessageRole.assistant)
        ]
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_completion_tokens,
            "temperature": request.temperature,
            "messages": turns,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in request.tools
            ]
        return payload

    def _parse(self, data: dict[str, Any]) -> LlmResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=str(block.get("id", "")),
                        name=str(block.get("name", "")),
                        arguments=dict(block.get("input", {})),
                    )
                )
        usage = data.get("usage", {})
        return LlmResponse(
            text="".join(text_parts),
            tool_calls=tuple(tool_calls),
            finish_reason=_FINISH.get(str(data.get("stop_reason")), FinishReason.stop),
            usage=TokenUsage(
                prompt_tokens=int(usage.get("input_tokens", 0)),
                completion_tokens=int(usage.get("output_tokens", 0)),
            ),
            model=str(data.get("model", "")),
            provider=self._info.name,
            from_live_provider=True,
        )

    async def complete(self, request: LlmRequest, *, timeout_s: float) -> LlmResponse:
        if not self._api_key:
            raise ProviderUnavailable(
                f"no API key for provider {self._info.name!r} "
                "(set SM_LLM_API_KEY); the AI layer will use deterministic templates"
            )
        client = self._http or httpx.AsyncClient(timeout=timeout_s)
        try:
            resp = await client.post(
                f"{self._base_url}/v1/messages",
                json=self._payload(request),
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(str(exc) or "llm request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"llm transport error: {exc}") from exc
        finally:
            if self._http is None:
                await client.aclose()

        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderUnavailable(f"provider returned {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderRefused(f"provider rejected the request ({resp.status_code})")
        return self._parse(resp.json())
