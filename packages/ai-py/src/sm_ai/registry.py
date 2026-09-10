"""`ToolRegistry` — the gate between an LLM tool request and a real capability.

Deny-by-default. For every `invoke`:

1. the tool must be registered            -> else `UnknownToolError`
2. the caller's principal must hold the tool's permission
                                           -> else `ToolAuthorizationError`
   (the LLM having asked for it is irrelevant)
3. the arguments must satisfy the args schema
                                           -> else `ToolInputInvalid`
4. the tool runs; its output is validated  -> else `ToolOutputInvalid`
5. an `AuditRecord` is emitted regardless of outcome.

`specs_for(principal)` returns only the `ToolSpec`s the principal is authorized
to use, so an unauthorized tool is never even offered to the model.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .errors import (
    AiError,
    ToolAuthorizationError,
    ToolInputInvalid,
    ToolOutputInvalid,
    UnknownToolError,
)
from .messages import ToolCall, ToolSpec
from .tools import Tool, ToolContext, ToolOutcome, ToolPrincipal

__all__ = ["ToolInvocationRecord", "ToolRegistry"]

AuditSink = Callable[["ToolInvocationRecord"], Awaitable[None]] | Callable[
    ["ToolInvocationRecord"], None
]


class ToolInvocationRecord:
    __slots__ = ("authorized", "correlation_id", "detail", "outcome", "principal", "tenant_id", "tool")

    def __init__(
        self,
        *,
        tool: str,
        principal: str,
        tenant_id: str,
        correlation_id: str,
        outcome: str,
        detail: str = "",
        authorized: bool,
    ) -> None:
        self.tool = tool
        self.principal = principal
        self.tenant_id = tenant_id
        self.correlation_id = correlation_id
        #: "ok" | "unknown_tool" | "denied" | "bad_input" | "bad_output" | "error"
        self.outcome = outcome
        self.detail = detail
        self.authorized = authorized


class ToolRegistry:
    def __init__(self, *, audit_sink: AuditSink | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._audit_sink = audit_sink

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def _authorized(self, tool: Tool, principal: ToolPrincipal) -> bool:
        if tool.required_permission is None:
            return True
        return principal.has_permission(tool.required_permission)

    def specs_for(self, principal: ToolPrincipal) -> tuple[ToolSpec, ...]:
        out: list[ToolSpec] = []
        for name in sorted(self._tools):
            tool = self._tools[name]
            if not self._authorized(tool, principal):
                continue
            out.append(
                ToolSpec(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.args_model.model_json_schema(),
                )
            )
        return tuple(out)

    async def _emit(self, record: ToolInvocationRecord) -> None:
        if self._audit_sink is None:
            return
        result = self._audit_sink(record)
        if asyncio.iscoroutine(result):
            await result

    async def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolOutcome:
        p = ctx.principal

        def _rec(outcome: str, detail: str = "", *, authorized: bool) -> ToolInvocationRecord:
            return ToolInvocationRecord(
                tool=call.name,
                principal=p.subject,
                tenant_id=str(p.tenant_id),
                correlation_id=ctx.correlation_id,
                outcome=outcome,
                detail=detail,
                authorized=authorized,
            )

        tool = self._tools.get(call.name)
        if tool is None:
            await self._emit(_rec("unknown_tool", authorized=False))
            raise UnknownToolError(f"no such tool: {call.name!r}")

        if not self._authorized(tool, p):
            await self._emit(
                _rec("denied", f"missing {tool.required_permission}", authorized=False)
            )
            raise ToolAuthorizationError(
                f"principal {p.subject!r} lacks {tool.required_permission} for {call.name!r}"
            )

        try:
            args = tool.args_model.model_validate(call.arguments)
        except Exception as exc:
            await self._emit(_rec("bad_input", str(exc)[:200], authorized=True))
            raise ToolInputInvalid(f"{call.name}: invalid arguments") from exc

        try:
            outcome = await tool.run(args, ctx)
        except ToolOutputInvalid as exc:
            await self._emit(_rec("bad_output", str(exc)[:200], authorized=True))
            raise
        except AiError:
            raise
        except Exception as exc:
            await self._emit(_rec("error", str(exc)[:200], authorized=True))
            raise

        await self._emit(
            _rec("ok" if outcome.ok else "error", outcome.error[:200], authorized=True)
        )
        return outcome
