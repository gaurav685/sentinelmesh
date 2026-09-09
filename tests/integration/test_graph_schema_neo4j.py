"""Phase 4 Unit 1 — real Neo4j: schema migration + driver behaviour.

Needs the compose `graph` profile:
    docker compose -f deploy/docker/docker-compose.yml --profile graph up -d neo4j
"""

from __future__ import annotations

import uuid

import pytest
from neo4j.exceptions import Neo4jError

from sm_common.graph import Graph, apply_pending, pending_versions

from .conftest import drop_graph_schema

pytestmark = pytest.mark.integration


async def _names(g: Graph, show: str) -> set[str]:
    return {row["name"] for row in await g.run_read(f"SHOW {show} YIELD name RETURN name")}


async def test_migration_creates_constraints_and_indexes(graph: Graph) -> None:
    constraints = await _names(graph, "CONSTRAINTS")
    assert {"host_uid", "identity_uid", "graph_command_id", "graph_migration_version"} <= constraints

    indexes = await _names(graph, "INDEXES")
    assert {"host_key", "identity_last_seen", "host_search", "domain_search"} <= indexes


async def test_migration_is_idempotent(graph: Graph) -> None:
    assert await pending_versions(graph) == []
    assert await apply_pending(graph) == []


async def test_migration_applies_from_bare_schema(graph: Graph) -> None:
    await drop_graph_schema(graph)
    assert "0001_schema" in await pending_versions(graph)

    ran = await apply_pending(graph)
    assert ran == ["0001_schema"]
    assert "host_uid" in await _names(graph, "CONSTRAINTS")


async def test_uid_uniqueness_is_enforced(graph: Graph) -> None:
    tid = uuid.uuid4()
    uid = f"{tid}:web01"
    await graph.run_write(
        "CREATE (h:Host {uid: $uid, tenant_id: $tid, host_id: 'web01'})",
        {"uid": uid, "tid": str(tid)},
    )
    with pytest.raises(Neo4jError):
        await graph.run_write(
            "CREATE (h:Host {uid: $uid, tenant_id: $tid, host_id: 'web01'})",
            {"uid": uid, "tid": str(tid)},
        )


async def test_parameterized_values_are_never_executed(graph: Graph) -> None:
    # A hostile string value must land as data, not Cypher.
    hostile = "web01'}) DETACH DELETE h //"
    await graph.run_write(
        "CREATE (h:Host {uid: $uid, tenant_id: $tid, hostname: $name})",
        {"uid": "t:h1", "tid": str(uuid.uuid4()), "name": hostile},
    )
    rows = await graph.run_read(
        "MATCH (h:Host {uid: $uid}) RETURN h.hostname AS name", {"uid": "t:h1"}
    )
    assert rows == [{"name": hostile}]


async def test_slow_query_hits_the_timeout(graph: Graph) -> None:
    tight = Graph(
        graph._driver,  # type: ignore[attr-defined]
        database="neo4j",
        query_timeout_ms=1,
    )
    with pytest.raises(Neo4jError):
        await tight.run_read("UNWIND range(1, 50000000) AS r RETURN count(r)")
