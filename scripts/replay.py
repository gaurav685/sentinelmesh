#!/usr/bin/env python3
"""Replay a Kafka topic into a consumer group by resetting its offsets to a time.

    python scripts/replay.py --topic events.canonical --group graph-writer-replay --since 2026-09-09T00:00:00Z
    python scripts/replay.py --topic events.canonical --group graph-writer-replay --since -2h --apply

Dry-run by default (prints the offsets it *would* seek to). `--apply` commits the
reset. The group MUST be a `*-replay` group (event-model.md §6): replaying into a
live group would re-fire side effects — a replay group runs with side-effecting
adapters disabled.

`--since` accepts an RFC3339 timestamp or a relative `-<n>[smhd]` (before now).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import UTC, datetime, timedelta

from aiokafka import AIOKafkaConsumer, TopicPartition

from sm_common.config import AppSettings

_REL = re.compile(r"^-(\d+)([smhd])$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_since(value: str) -> datetime:
    m = _REL.match(value)
    if m:
        return datetime.now(UTC) - timedelta(seconds=int(m.group(1)) * _UNIT[m.group(2)])
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _run(topic: str, group: str, since: datetime, apply: bool) -> int:
    if not group.endswith("-replay"):
        print(f"refusing: '{group}' is not a *-replay group (event-model.md §6)", file=sys.stderr)
        return 2

    settings = AppSettings(service_name="replay")
    consumer = AIOKafkaConsumer(
        topic, bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=group, client_id="replay", enable_auto_commit=False,
        security_protocol=settings.kafka_security_protocol,
    )
    await consumer.start()
    try:
        await consumer.getmany(timeout_ms=2000)  # force assignment
        assignment = consumer.assignment()
        if not assignment:
            print(f"no partitions assigned for {topic!r} in group {group!r}", file=sys.stderr)
            return 1
        ms = int(since.timestamp() * 1000)
        offsets = await consumer.offsets_for_times({tp: ms for tp in assignment})
        targets: dict[TopicPartition, int] = {}
        for tp, meta in offsets.items():
            targets[tp] = meta.offset if meta is not None else (await consumer.end_offsets([tp]))[tp]

        for tp, off in sorted(targets.items(), key=lambda kv: kv[0].partition):
            print(f"  {tp.topic}-{tp.partition} -> offset {off}")

        if not apply:
            print(f"dry-run — pass --apply to commit these offsets for group {group!r}")
            return 0

        for tp, off in targets.items():
            consumer.seek(tp, off)
        await consumer.commit({tp: off for tp, off in targets.items()})
        print(f"committed: group {group!r} will reprocess {topic!r} from {since.isoformat()}")
        return 0
    finally:
        await consumer.stop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--group", required=True, help="must end with '-replay'")
    ap.add_argument("--since", required=True, help="RFC3339 timestamp or -<n>[smhd]")
    ap.add_argument("--apply", action="store_true", help="commit the offset reset (default: dry-run)")
    args = ap.parse_args()
    sys.exit(asyncio.run(_run(args.topic, args.group, _parse_since(args.since), args.apply)))


if __name__ == "__main__":
    main()
