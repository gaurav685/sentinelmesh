from __future__ import annotations

import uuid

from sm_correlation_engine.graph import chain_graph_commands

from sm_contracts import GraphOp, ThreatSubjectType

from .conftest import _chain_model, detection_payload, envelope_for


def _cmds(**chain_over: object):
    chain = _chain_model(**chain_over)
    source = envelope_for(detection_payload())
    return chain, chain_graph_commands(source, chain)


def test_a_chain_projects_a_node_an_involves_edge_and_mapped_to_edges() -> None:
    chain, envs = _cmds(subject_type=ThreatSubjectType.host, subject_id="web01",
                        technique_ids=["T1110", "T1021"])
    ops = [e.payload for e in envs]
    node = next(p for p in ops if p.op is GraphOp.merge_node)
    assert node.label == ":AttackChain"
    assert node.key == {"chain_id": str(chain.id)}
    assert node.props["subject_id"] == "web01"

    involves = next(p for p in ops if p.label == "INVOLVES")
    assert involves.start.label == ":AttackChain"
    assert involves.end.label == ":Host"
    assert involves.end.key == {"host_id": "web01"}

    mapped = [p for p in ops if p.label == "MAPPED_TO"]
    assert {p.end.key["technique_id"] for p in mapped} == {"T1110", "T1021"}


def test_command_ids_are_deterministic_per_chain() -> None:
    _, a = _cmds(id=uuid.UUID(int=42), technique_ids=["T1110"])
    _, b = _cmds(id=uuid.UUID(int=42), technique_ids=["T1110"])
    assert [e.payload.command_id for e in a] == [e.payload.command_id for e in b]


def test_a_detection_subject_gets_a_node_but_no_involves_edge() -> None:
    _, envs = _cmds(subject_type=ThreatSubjectType.detection, subject_id=str(uuid.uuid4()),
                    technique_ids=[])
    labels = [e.payload.label for e in envs]
    assert labels == [":AttackChain"]  # no INVOLVES for a non-entity subject
