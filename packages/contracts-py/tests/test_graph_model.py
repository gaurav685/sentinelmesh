"""The Neo4j label / relationship allowlist must track docs/architecture/data-model.md.

Cypher cannot parameterize a label or a relationship type, so `graph-service`
string-builds those after checking them against these sets. If the allowlist
drifts from the locked model, a valid command is dead-lettered or an invalid one
slips through — this test is the guard on the guard.
"""

from __future__ import annotations

import uuid

from sm_contracts import (
    GRAPH_NODE_KEY,
    GRAPH_NODE_LABELS,
    GRAPH_REL_TYPES,
    GraphOp,
    graph_command_id,
    graph_node_uid,
    normalize_label,
)

# docs/architecture/data-model.md "Node labels" table, verbatim.
_MODEL_NODE_KEYS = {
    "Tenant": "tenant_id",
    "Identity": "identity_id",
    "Host": "host_id",
    "IpAddress": "ip",
    "Domain": "fqdn",
    "Process": "process_id",
    "File": "file_id",
    "Sensor": "sensor_id",
    "Detection": "detection_id",
    "AttackChain": "chain_id",
    "AttackTechnique": "technique_id",
    "ThreatActor": "actor_id",
    "Campaign": "campaign_id",
}

# docs/architecture/data-model.md "Relationship types" — the canonical set.
_MODEL_REL_TYPES = {
    "AUTHENTICATED_TO",
    "LOGGED_INTO",
    "CONNECTED_TO",
    "RESOLVED",
    "RESOLVES_TO",
    "EXECUTED",
    "DOWNLOADED",
    "SPAWNED",
    "USED_CREDENTIAL_ON",
    "INVOLVES",
    "HAS_STAGE",
    "MAPPED_TO",
    "INCLUDES",
    "ATTRIBUTED",
}


def test_node_key_map_matches_locked_model() -> None:
    assert GRAPH_NODE_KEY == _MODEL_NODE_KEYS


def test_node_labels_frozenset_is_the_key_map_keys() -> None:
    assert GRAPH_NODE_LABELS == frozenset(_MODEL_NODE_KEYS)


def test_every_canonical_relationship_is_allowlisted() -> None:
    assert _MODEL_REL_TYPES <= GRAPH_REL_TYPES


def test_relationship_extras_are_documented() -> None:
    # data-model.md marks the set "extensible"; ACCESSED is used by the
    # stream-processor file-access mapper. Nothing else may be added silently.
    assert GRAPH_REL_TYPES - _MODEL_REL_TYPES == {"ACCESSED"}


def test_normalize_label_strips_leading_colon() -> None:
    assert normalize_label(":Host") == "Host"
    assert normalize_label("Host") == "Host"


def test_graph_node_uid_is_tenant_scoped() -> None:
    tid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert graph_node_uid(tid, "web01") == f"{tid}:web01"
    # different tenants never collide on the same natural key
    other = uuid.UUID("22222222-2222-2222-2222-222222222222")
    assert graph_node_uid(tid, "web01") != graph_node_uid(other, "web01")


def test_graph_command_id_is_deterministic() -> None:
    raw = uuid.uuid4()
    a = graph_command_id(raw, GraphOp.merge_node, ":Host", "host01")
    b = graph_command_id(raw, GraphOp.merge_node, ":Host", "host01")
    c = graph_command_id(raw, GraphOp.merge_node, ":Host", "host02")
    assert a == b
    assert a != c
