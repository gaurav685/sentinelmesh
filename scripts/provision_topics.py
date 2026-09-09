#!/usr/bin/env python3
"""Create the Kafka topic catalog on a local / CI broker.

    python scripts/provision_topics.py            # whole catalog + every .dlq
    python scripts/provision_topics.py --list     # print the catalog, create nothing

Partition counts / retention come from `sm_contracts.topics.TOPICS`. Idempotent
(create-if-absent). A real deployment provisions topics via IaC, not this.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sm_common.bus import ensure_topics
from sm_common.config import AppSettings
from sm_contracts import TOPICS, dlq_topic


def _settings() -> AppSettings:
    return AppSettings(service_name="topics-init")  # SM_KAFKA_* from the env


async def _run(list_only: bool) -> int:
    if list_only:
        for spec in TOPICS.values():
            print(
                f"{spec.name:20s} p={spec.partitions:<3d} key={spec.key:16s} "
                f"retention={spec.retention:8s} cleanup={spec.cleanup}"
                + (f"  (+ {dlq_topic(spec.name)})" if spec.has_dlq else "")
            )
        return 0
    created = await ensure_topics(_settings())
    print(f"created: {created}" if created else "nothing to create — catalog already present")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="print the catalog, create nothing")
    args = ap.parse_args()
    sys.exit(asyncio.run(_run(args.list)))


if __name__ == "__main__":
    main()
