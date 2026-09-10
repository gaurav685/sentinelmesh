"""The authorized-tool contract.

Every capability the AI layer can invoke is a `Tool` with:

- an explicit Pydantic `args_model` (the model only ever sees its JSON Schema);
- an optional `required_permission` — checked against the **caller's** principal,
  never granted because the LLM asked;
- input validation (the args_model), and output validation (`result_model`);
- an audit record for every invocation, success or failure.

Tools never see the raw LLM text and never make an authorization decision of
their own — the registry does that before `run` is called.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from sm_contracts import PermissionCode

from .errors import ToolInputInvalid, ToolOutputInvalid

__all__ = [
    "FunctionTool",
    "Tool",
    "ToolContext",
    "ToolOutcome",
    "ToolPrincipal",
]

ArgsT = TypeVar("ArgsT", bound=BaseModel)


class ToolPrincipal(Protocol):
    """The minimal view of the caller a tool needs. The AI service adapts its
    real principal (a session `Principal` or a minted agent identity) to this."""

    @property
    def tenant_id(self) -> UUID: ...

    @property
    def subject(self) -> str: ...

    def has_permission(self, code: PermissionCode) -> bool: ...


@dataclass(frozen=True)
class ToolContext:
    principal: ToolPrincipal
    correlation_id: str
    #: Set by the orchestrator; a tool may check it for long work.
    deadline_s: float | None = None


@dataclass
class ToolOutcome:
    ok: bool
    #: A short, model-facing rendering of the result (already safe to show the
    #: model — a tool must not embed raw untrusted text here without fencing).
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class Tool(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]
    result_model: type[BaseModel] | None
    required_permission: PermissionCode | None

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome: ...


@dataclass
class FunctionTool(Generic[ArgsT]):
    """Wrap an async function as a `Tool`."""

    name: str
    description: str
    args_model: type[ArgsT]
    handler: Callable[[ArgsT, ToolContext], Awaitable[ToolOutcome]]
    required_permission: PermissionCode | None = None
    result_model: type[BaseModel] | None = None

    def parse_args(self, raw: dict[str, Any]) -> ArgsT:
        try:
            return self.args_model.model_validate(raw)
        except ValidationError as exc:
            raise ToolInputInvalid(f"{self.name}: {exc.error_count()} invalid argument(s)") from exc

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        if not isinstance(args, self.args_model):
            raise ToolInputInvalid(f"{self.name}: wrong argument model")
        outcome = await self.handler(args, ctx)
        if outcome.ok and self.result_model is not None:
            try:
                self.result_model.model_validate(outcome.data)
            except ValidationError as exc:
                raise ToolOutputInvalid(f"{self.name}: output failed its schema — {exc}") from exc
        return outcome
