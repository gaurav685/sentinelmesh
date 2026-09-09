from __future__ import annotations

from typing import Any

from sm_contracts import CanonicalKind, GraphOp
from sm_stream_processor.emitter import emit


def _by_op(cmds: list, op: GraphOp) -> list:
    return [c for c in cmds if c.payload.op is op]


def test_network_flow_emits_two_ip_nodes_and_a_connected_to_edge(make_canonical_fn: Any) -> None:
    env = make_canonical_fn(
        CanonicalKind.network_flow, actor_value="10.0.0.1", target_value="8.8.8.8",
        attributes={"dst_port": 443, "protocol": "tcp", "bytes_sent": 1200},
    )
    cmds = emit(env)
    nodes = _by_op(cmds, GraphOp.merge_node)
    edges = _by_op(cmds, GraphOp.merge_edge)
    assert {c.payload.label for c in nodes} == {":IpAddress"}
    assert {tuple(c.payload.key.items()) for c in nodes} == {
        (("ip", "10.0.0.1"),), (("ip", "8.8.8.8"),)
    }
    assert len(edges) == 1
    e = edges[0].payload
    assert e.label == "CONNECTED_TO"
    assert e.start.label == ":IpAddress" and e.start.key == {"ip": "10.0.0.1"}
    assert e.end.key == {"ip": "8.8.8.8"}
    assert e.props["dst_port"] == 443 and e.props["protocol"] == "tcp"
    assert e.props["action"] == "connected_to"


def test_auth_maps_identity_to_host(make_canonical_fn: Any) -> None:
    env = make_canonical_fn(CanonicalKind.auth, actor_value="alice@corp", target_value="dc01")
    cmds = emit(env)
    edge = _by_op(cmds, GraphOp.merge_edge)[0].payload
    assert edge.label == "AUTHENTICATED_TO"
    assert edge.start.label == ":Identity" and edge.end.label == ":Host"


def test_every_command_envelope_is_a_graph_command(make_canonical_fn: Any) -> None:
    env = make_canonical_fn(CanonicalKind.dns, actor_value="10.0.0.5", target_value="evil.example")
    for cmd in emit(env):
        assert cmd.event_type.value == "graph.command"
        assert cmd.event_id == cmd.payload.command_id
        assert cmd.tenant_id == env.tenant_id
        assert cmd.payload.raw_event_id == env.payload.raw_event_id
        assert cmd.metadata["raw_event_id"] == str(env.payload.raw_event_id)


def test_command_ids_are_deterministic_in_the_source_event(make_canonical_fn: Any) -> None:
    env = make_canonical_fn(
        CanonicalKind.process_exec, actor_value="web01", target_value="powershell.exe"
    )
    ids_a = sorted(str(c.payload.command_id) for c in emit(env))
    ids_b = sorted(str(c.payload.command_id) for c in emit(env))
    assert ids_a == ids_b
    assert len(set(ids_a)) == len(ids_a)  # no collisions between the node/edge commands


def test_extra_entities_become_nodes(make_canonical_fn: Any) -> None:
    from sm_contracts import EntityKind, EntityRef

    env = make_canonical_fn(
        CanonicalKind.dns, actor_value="10.0.0.5", target_value="evil.example",
        extra_entities=[EntityRef(kind=EntityKind.ip, value="93.184.216.34")],
    )
    node_keys = {tuple(c.payload.key.items()) for c in emit(env) if c.payload.op is GraphOp.merge_node}
    assert (("ip", "93.184.216.34"),) in node_keys
