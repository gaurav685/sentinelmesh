from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from sm_ai.errors import ToolAuthorizationError, ToolInputInvalid, ToolOutputInvalid, UnknownToolError
from sm_ai.messages import ToolCall
from sm_ai.registry import ToolInvocationRecord, ToolRegistry
from sm_ai.tools import FunctionTool, ToolContext, ToolOutcome
from sm_contracts import PermissionCode

from .conftest import FakePrincipal


class _Args(BaseModel):
    entity: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


class _Out(BaseModel):
    count: int


def _ctx(principal: FakePrincipal) -> ToolContext:
    return ToolContext(principal=principal, correlation_id="corr-1")


def _lookup_tool(**overrides: object) -> FunctionTool:
    async def handler(args: _Args, ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(ok=True, content=f"{args.entity}: 3 hits", data={"count": 3})

    kw: dict[str, object] = {
        "name": "lookup_entity",
        "description": "Look up an entity's recent detections.",
        "args_model": _Args,
        "handler": handler,
        "required_permission": PermissionCode.detections_read,
        "result_model": _Out,
    }
    kw.update(overrides)
    return FunctionTool(**kw)  # type: ignore[arg-type]


async def test_specs_only_lists_authorized_tools() -> None:
    reg = ToolRegistry()
    reg.register(_lookup_tool())
    assert reg.specs_for(FakePrincipal(grants=set())) == ()
    specs = reg.specs_for(FakePrincipal(grants={PermissionCode.detections_read}))
    assert [s.name for s in specs] == ["lookup_entity"]
    assert specs[0].parameters["properties"].keys() >= {"entity", "limit"}


async def test_unknown_tool_is_rejected_and_audited() -> None:
    records: list[ToolInvocationRecord] = []
    reg = ToolRegistry(audit_sink=records.append)
    with pytest.raises(UnknownToolError):
        await reg.invoke(ToolCall(id="1", name="nope", arguments={}), _ctx(FakePrincipal()))
    assert records[-1].outcome == "unknown_tool" and records[-1].authorized is False


async def test_an_unauthorized_call_is_denied_even_though_the_llm_asked() -> None:
    records: list[ToolInvocationRecord] = []
    reg = ToolRegistry(audit_sink=records.append)
    reg.register(_lookup_tool())
    # The model produced a well-formed call for a real tool — authorization is
    # still the principal's, not the model's.
    with pytest.raises(ToolAuthorizationError):
        await reg.invoke(
            ToolCall(id="1", name="lookup_entity", arguments={"entity": "svc-x"}),
            _ctx(FakePrincipal(grants=set())),
        )
    assert records[-1].outcome == "denied"


async def test_bad_arguments_are_rejected() -> None:
    reg = ToolRegistry()
    reg.register(_lookup_tool())
    ctx = _ctx(FakePrincipal(grants={PermissionCode.detections_read}))
    with pytest.raises(ToolInputInvalid):
        await reg.invoke(
            ToolCall(id="1", name="lookup_entity", arguments={"entity": "", "limit": 999}), ctx
        )


async def test_output_that_fails_its_schema_is_surfaced_not_passed_on() -> None:
    async def bad_handler(args: _Args, ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(ok=True, content="x", data={"count": "not-an-int"})

    reg = ToolRegistry()
    reg.register(_lookup_tool(handler=bad_handler))
    ctx = _ctx(FakePrincipal(grants={PermissionCode.detections_read}))
    with pytest.raises(ToolOutputInvalid):
        await reg.invoke(
            ToolCall(id="1", name="lookup_entity", arguments={"entity": "svc-x"}), ctx
        )


async def test_a_happy_call_runs_and_audits_ok() -> None:
    records: list[ToolInvocationRecord] = []
    reg = ToolRegistry(audit_sink=records.append)
    reg.register(_lookup_tool())
    ctx = _ctx(FakePrincipal(grants={PermissionCode.detections_read}))
    out = await reg.invoke(
        ToolCall(id="1", name="lookup_entity", arguments={"entity": "svc-x"}), ctx
    )
    assert out.ok and out.data == {"count": 3}
    assert records[-1].outcome == "ok" and records[-1].authorized is True


async def test_a_tool_with_no_permission_requirement_is_open() -> None:
    reg = ToolRegistry()
    reg.register(_lookup_tool(required_permission=None, result_model=None))
    out = await reg.invoke(
        ToolCall(id="1", name="lookup_entity", arguments={"entity": "z"}),
        _ctx(FakePrincipal(grants=set())),
    )
    assert out.ok


def test_registering_a_duplicate_name_raises() -> None:
    reg = ToolRegistry()
    reg.register(_lookup_tool())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_lookup_tool())
