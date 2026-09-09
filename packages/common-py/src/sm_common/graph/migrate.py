"""Versioned Cypher schema migrations (docs/architecture/data-model.md).

Neo4j has no Alembic. This is the equivalent: `.cypher` files named
``NNNN_name.cypher`` under ``migrations/neo4j/``, applied in filename order,
each recorded as a ``:_GraphMigration {version}`` node so a second run is a
no-op. Every statement in a file is expected to be ``IF NOT EXISTS`` as a second
line of defence.

    from sm_common.graph import Graph, apply_pending, MIGRATIONS_DIR
    async with Graph.from_settings(settings) as g:
        await apply_pending(g, MIGRATIONS_DIR)
"""

from __future__ import annotations

from pathlib import Path

import structlog

from .driver import Graph

__all__ = ["MIGRATIONS_DIR", "apply_pending", "pending_versions", "split_statements"]

_log = structlog.get_logger("sm.graph.migrate")

# repo-root/migrations/neo4j — five parents up from this file
# (.../packages/common-py/src/sm_common/graph/migrate.py)
MIGRATIONS_DIR = Path(__file__).resolve().parents[5] / "migrations" / "neo4j"

_LEDGER_LABEL = "_GraphMigration"


def split_statements(text: str) -> list[str]:
    """`.cypher` file -> individual statements. Strips `//` comment lines, then
    splits on `;`. Cypher schema statements contain no string literals with a
    semicolon, so a plain split is safe here."""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("//")]
    body = "\n".join(lines)
    return [stmt.strip() for stmt in body.split(";") if stmt.strip()]


async def _applied_versions(graph: Graph) -> set[str]:
    rows = await graph.run_read(f"MATCH (m:{_LEDGER_LABEL}) RETURN m.version AS version")
    return {row["version"] for row in rows}


def _migration_files(migrations_dir: Path) -> list[Path]:
    return sorted(migrations_dir.glob("[0-9]*.cypher"))


async def pending_versions(graph: Graph, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    applied = await _applied_versions(graph)
    return [p.stem for p in _migration_files(migrations_dir) if p.stem not in applied]


async def apply_pending(graph: Graph, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration file not yet recorded. Returns the versions applied."""
    # The ledger constraint lives inside 0001; guarantee the label exists so the
    # very first read does not fail on an empty database.
    await graph.run_write(
        f"CREATE CONSTRAINT graph_migration_version IF NOT EXISTS "
        f"FOR (m:{_LEDGER_LABEL}) REQUIRE m.version IS UNIQUE"
    )
    applied = await _applied_versions(graph)
    ran: list[str] = []
    for path in _migration_files(migrations_dir):
        version = path.stem
        if version in applied:
            continue
        statements = split_statements(path.read_text(encoding="utf-8"))
        _log.info("graph.migration.apply", version=version, statements=len(statements))
        for stmt in statements:
            await graph.run_write(stmt)
        await graph.run_write(
            f"MERGE (m:{_LEDGER_LABEL} {{version: $version}}) "
            f"ON CREATE SET m.applied_at = datetime()",
            {"version": version},
        )
        ran.append(version)
    return ran
