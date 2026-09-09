#!/usr/bin/env python3
"""Import a MITRE ATT&CK STIX 2.1 bundle into the `mitre-service` catalog.

    python scripts/import_attack_stix.py --bundle ./enterprise-attack.json --version 14.1

The bundle is NOT committed to this repository (ADR-024). Download the pinned
version from the MITRE CTI repo and pass its path. The import replaces the whole
catalog for that version in one transaction and records `attack_matrix_version`
(counts + the bundle's sha256) — the service never claims coverage beyond it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sm_mitre_service.catalog import CatalogRepository
from sm_mitre_service.stix import bundle_sha256, parse_stix_bundle

from sm_common.config import AppSettings
from sm_common.db import Database


async def _run(raw: bytes, version: str, source: str) -> int:
    parsed = parse_stix_bundle(raw, version=version, source=source)
    db = Database.from_settings(AppSettings(service_name="mitre-import"))
    try:
        result = await CatalogRepository(db).import_catalog(parsed, bundle_sha256=bundle_sha256(raw))
    finally:
        await db.dispose()
    print(
        f"imported version {result.version}: {result.tactic_count} tactics, "
        f"{result.technique_count} techniques, {result.subtechnique_count} sub-techniques "
        f"(sha256 {result.stix_bundle_sha256[:12]})"
    )
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True, type=Path, help="path to the ATT&CK STIX 2.1 bundle")
    ap.add_argument("--version", required=True, help="matrix version label, e.g. '14.1'")
    ap.add_argument("--source", default="mitre/enterprise")
    args = ap.parse_args()
    if not args.bundle.exists():
        sys.exit(f"bundle not found: {args.bundle}")
    raw = args.bundle.read_bytes()
    sys.exit(asyncio.run(_run(raw, args.version, args.source)))


if __name__ == "__main__":
    main()
