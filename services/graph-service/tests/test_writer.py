from __future__ import annotations

import pytest

from sm_common.bus import PoisonError
from sm_contracts import GraphEndpoint, GraphMutationOutcome, GraphOp
from sm_graph_service.writer import GraphWriter

from .conftest import FakeGraph, edge_command, node_command


@pytest.fixture
def writer(rig) -> GraphWriter:  # type: ignore[no-untyped-def]
    return rig.writer


async def test_unknown_node_label_is_poison(writer: GraphWriter) -> None:
    with pytest.raises(PoisonError, match="allowlist"):
        await writer.apply(node_command(label=":Wormhole", key={"host_id": "x"}))


async def test_unknown_relationship_type_is_poison(writer: GraphWriter) -> None:
    with pytest.raises(PoisonError, match="allowlist"):
        await writer.apply(edge_command(label="PWNED"))


async def test_node_key_must_match_the_label(writer: GraphWriter) -> None:
    with pytest.raises(PoisonError, match="key must be exactly"):
        await writer.apply(node_command(label=":Host", key={"ip": "10.0.0.1"}))


async def test_prune_is_not_implemented_yet(writer: GraphWriter) -> None:
    with pytest.raises(PoisonError, match="not implemented"):
        await writer.apply(node_command(op=GraphOp.prune))


async def test_edge_without_endpoints_is_poison(writer: GraphWriter) -> None:
    cmd = edge_command()
    cmd = cmd.model_copy(update={"start": None})
    with pytest.raises(PoisonError, match="missing start / end"):
        await writer.apply(cmd)


async def test_duplicate_command_id_short_circuits(rig) -> None:  # type: ignore[no-untyped-def]
    graph: FakeGraph = rig.graph
    cmd = node_command()
    graph.applied_ids.add(str(cmd.command_id))
    result = await rig.writer.apply(cmd)
    assert result.outcome is GraphMutationOutcome.duplicate
    # no MERGE (n:Host ...) mutation was attempted
    assert not any("MERGE (n:`Host`" in c for c, _ in graph.writes)


async def test_node_merge_is_parameterized_and_tenant_scoped(rig) -> None:  # type: ignore[no-untyped-def]
    graph: FakeGraph = rig.graph
    cmd = node_command(props={"hostname": "web01", "uid": "haxx", "tenant_id": "haxx"})
    result = await rig.writer.apply(cmd)
    assert result.outcome is GraphMutationOutcome.applied
    assert result.nodes_written == 1

    cypher, params = next((c, p) for c, p in graph.writes if "MERGE (n:`Host`" in c)
    # the natural-key value is never interpolated into the query text
    assert "web01" not in cypher
    assert params["uid"] == f"{cmd.tenant_id}:web01"
    assert params["tenant_id"] == str(cmd.tenant_id)
    # writer-owned props are stripped from the caller-supplied map
    assert params["props"] == {"hostname": "web01"}


async def test_stale_node_when_watermark_is_newer(rig) -> None:  # type: ignore[no-untyped-def]
    rig.graph.write_rows = [{"current": False}]
    result = await rig.writer.apply(node_command())
    assert result.outcome is GraphMutationOutcome.stale
    assert result.nodes_written == 0


async def test_edge_merge_uses_backticked_allowlisted_type(rig) -> None:  # type: ignore[no-untyped-def]
    graph: FakeGraph = rig.graph
    result = await rig.writer.apply(
        edge_command(
            label="CONNECTED_TO",
            start=GraphEndpoint(label=":Host", key={"host_id": "web01"}),
            end=GraphEndpoint(label=":IpAddress", key={"ip": "10.0.0.9"}),
            props={"port": 443},
        )
    )
    assert result.outcome is GraphMutationOutcome.applied
    assert (result.nodes_written, result.relationships_written) == (2, 1)
    cypher, params = next((c, p) for c, p in graph.writes if "-[r:`CONNECTED_TO`]->" in c)
    assert "10.0.0.9" not in cypher
    assert params["start_uid"].endswith(":web01")
    assert params["end_uid"].endswith(":10.0.0.9")
    assert params["props"] == {"port": 443}


async def test_ledger_is_written_after_a_successful_mutation(rig) -> None:  # type: ignore[no-untyped-def]
    await rig.writer.apply(node_command())
    assert any("MERGE (c:_GraphCommand" in c for c, _ in rig.graph.writes)
