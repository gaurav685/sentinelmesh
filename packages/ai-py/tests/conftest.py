from __future__ import annotations

import asyncio
import uuid
from uuid import UUID

from sm_ai.messages import FinishReason, LlmMessage, LlmRequest, LlmResponse, MessageRole, TokenUsage
from sm_ai.provider import ProviderInfo
from sm_contracts import PermissionCode

__all__ = ["FakePrincipal", "ScriptedProvider", "make_request", "user_msg"]


class FakePrincipal:
    """A `ToolPrincipal` for tests — holds an explicit permission set."""

    def __init__(
        self, *, subject: str = "agent:detection", grants: set[PermissionCode] | None = None,
        tenant_id: UUID | None = None,
    ) -> None:
        self._subject = subject
        self._grants = grants or set()
        self._tenant = tenant_id or uuid.uuid4()

    @property
    def tenant_id(self) -> UUID:
        return self._tenant

    @property
    def subject(self) -> str:
        return self._subject

    def has_permission(self, code: PermissionCode) -> bool:
        return code in self._grants


def user_msg(text: str) -> LlmMessage:
    return LlmMessage(role=MessageRole.user, content=text)


def make_request(*texts: str, model: str = "test-model", purpose: str = "unit") -> LlmRequest:
    return LlmRequest(
        model=model,
        messages=tuple(user_msg(t) for t in (texts or ("hello",))),
        purpose=purpose,
    )


class ScriptedProvider:
    """A provider whose outcome for each call is scripted. Records every request.

    An outcome is a `str` (wrapped in an `LlmResponse`), an `LlmResponse`, or an
    `Exception` to raise. The last outcome repeats once the list is exhausted.
    """

    def __init__(
        self,
        outcomes: list[str | LlmResponse | Exception],
        *,
        name: str = "scripted",
        is_live: bool = False,
        sleep_s: float = 0.0,
    ) -> None:
        self._outcomes = outcomes
        self._i = 0
        self.calls: list[LlmRequest] = []
        self._info = ProviderInfo(name, supports_tools=True, is_live=is_live)
        self._sleep_s = sleep_s

    @property
    def info(self) -> ProviderInfo:
        return self._info

    async def complete(self, request: LlmRequest, *, timeout_s: float) -> LlmResponse:
        self.calls.append(request)
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        outcome = self._outcomes[min(self._i, len(self._outcomes) - 1)]
        self._i += 1
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, LlmResponse):
            return outcome
        return LlmResponse(
            text=outcome,
            finish_reason=FinishReason.stop,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            model=request.model,
            provider=self._info.name,
            from_live_provider=self._info.is_live,
        )
