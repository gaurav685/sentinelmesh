#!/usr/bin/env python3
"""Apply the Neo4j schema migrations (migrations/neo4j/*.cypher).

    python scripts/graph_migrate.py            # apply everything pending
    python scripts/graph_migrate.py --status   # list applied / pending, change nothing

Target Neo4j comes from the validated `AppSettings` (`SM_NEO4J_*`), same as the
service — no connection string on the command line. Idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sm_common.config import AppSettings
from sm_common.graph import Graph, apply_pending, pending_versions


def _settings() -> AppSettings:
    return AppSettings(service_name="graph-migrations")  # SM_NEO4J_* from the env


async def _run(status_only: bool) -> int:
    async with Graph.from_settings(_settings()) as graph:
        if status_only:
            pending = await pending_versions(graph)
            print("pending: " + (", ".join(pending) if pending else "none — schema up to date"))
            return 0
        ran = await apply_pending(graph)
        print(f"applied: {', '.join(ran)}" if ran else "nothing to apply — schema up to date")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="list applied / pending, change nothing")
    args = ap.parse_args()
    sys.exit(asyncio.run(_run(args.status)))


if __name__ == "__main__":
    main()
