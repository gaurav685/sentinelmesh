from __future__ import annotations

import re
import uuid

import pytest

from sm_common.errors import ValidationFailed
from sm_contracts import EntitySelector, QueryLimits, QueryPlan
from sm_graph_service.hunt import compile_plan, validate_plan

TENANT = uuid.uuid4()
_WRITE_KEYWORDS = re.compile(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|CALL)\b", re.I)


def _plan(intent: str, *selectors: tuple[str, str], **kw: object) -> QueryPlan:
    return QueryPlan(
        intent=intent,  # type: ignore[arg-type]
        selectors=[EntitySelector(type=t, value=v) for t, v in selectors],  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


def _compile(plan: QueryPlan):
    return compile_plan(plan, TENANT, max_rows=200, max_depth=3)


@pytest.mark.parametrize(
    ("intent", "selectors"),
    [
        ("find_entity", [("host", "web01")]),
        ("list_related", [("identity", "svc-backup")]),
        ("path_between", [("identity", "svc-backup"), ("host", "web01")]),
        ("detections_for", [("host", "web01")]),
        ("chains_for", [("identity", "svc-backup")]),
        ("indicator_sightings", [("ip", "10.0.0.9")]),
        ("technique_usage", [("attack_technique", "T1110")]),
    ],
)
def test_every_intent_compiles_to_a_read_only_parameterized_query(
    intent: str, selectors: list[tuple[str, str]]
) -> None:
    compiled = _compile(_plan(intent, *selectors))
    assert _WRITE_KEYWORDS.search(compiled.cypher) is None
    assert "$tenant" in compiled.cypher
    assert compiled.params["tenant"] == str(TENANT)
    # every selector value is a bound parameter, never in the query text
    for i, (_t, v) in enumerate(selectors):
        assert compiled.params[f"v{i}"] == v
        assert v not in compiled.cypher


def test_a_cypher_injection_string_in_a_selector_value_stays_a_parameter() -> None:
    hostile = "web01' }) DETACH DELETE (n) //"
    compiled = _compile(_plan("find_entity", ("host", hostile)))
    assert hostile not in compiled.cypher
    assert compiled.params["v0"] == hostile
    assert _WRITE_KEYWORDS.search(compiled.cypher) is None


def test_path_between_needs_exactly_two_selectors() -> None:
    with pytest.raises(ValidationFailed, match="2 selector"):
        validate_plan(_plan("path_between", ("host", "web01")))


def test_technique_usage_rejects_a_non_technique_selector() -> None:
    with pytest.raises(ValidationFailed, match="not valid for intent"):
        validate_plan(_plan("technique_usage", ("host", "web01")))


def test_an_unknown_relationship_type_is_rejected() -> None:
    with pytest.raises(ValidationFailed, match="unknown relationship type"):
        validate_plan(_plan("list_related", ("host", "web01"), rel_types=["DROP_TABLE"]))


def test_rel_types_are_only_valid_for_list_related() -> None:
    with pytest.raises(ValidationFailed, match="only valid for"):
        validate_plan(_plan("detections_for", ("host", "web01"), rel_types=["CONNECTED_TO"]))


def test_a_known_relationship_type_filter_is_applied() -> None:
    compiled = _compile(_plan("list_related", ("host", "web01"), rel_types=["CONNECTED_TO"]))
    assert ":CONNECTED_TO*1.." in compiled.cypher


def test_depth_and_rows_are_clamped_to_the_server_ceiling() -> None:
    plan = _plan("list_related", ("host", "web01"), limits=QueryLimits(max_depth=4, max_rows=500))
    compiled = _compile(plan)
    assert "*1..3" in compiled.cypher  # server hunt_max_depth = 3, below the plan's 4
    assert compiled.params["cap"] == 200  # server hunt_max_rows


def test_the_fingerprint_is_deterministic_and_intent_specific() -> None:
    a = _compile(_plan("find_entity", ("host", "web01")))
    b = _compile(_plan("find_entity", ("host", "web99")))  # different value, same template
    c = _compile(_plan("list_related", ("host", "web01")))
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != c.fingerprint


def test_tenant_comes_from_the_argument_and_there_is_no_plan_field_for_it() -> None:
    other = uuid.uuid4()
    compiled = compile_plan(
        _plan("find_entity", ("host", "web01")), other, max_rows=200, max_depth=3
    )
    assert compiled.params["tenant"] == str(other)
    # the plan has no tenant field at all — it cannot widen scope
    assert "tenant" not in QueryPlan.model_fields
    assert "tenant_id" not in QueryPlan.model_fields
