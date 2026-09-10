#!/usr/bin/env python3
"""Generate JSON Schema (and, if tooling is present, TypeScript) from sm_contracts.

Pipeline:  sm_contracts (Pydantic v2)  ->  packages/contracts-ts/schemas/*.json
           -> (optional) packages/contracts-ts/src/*.ts

The JSON Schema step is pure Python and always runs. The TypeScript step needs
`json-schema-to-typescript` installed under `packages/contracts-ts`
(`npm install`); if it is missing this script prints how to enable it and exits 0
(JSON Schema is still written).

Usage:
    python scripts/gen_contracts.py [--check]

--check : do not write; exit non-zero if the generated JSON Schema would differ
          from what is committed (for CI).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_PY_SRC = REPO_ROOT / "packages" / "contracts-py" / "src"
SCHEMA_DIR = REPO_ROOT / "packages" / "contracts-ts" / "schemas"
TS_DIR = REPO_ROOT / "packages" / "contracts-ts" / "src"

sys.path.insert(0, str(CONTRACTS_PY_SRC))


def _render_schemas() -> dict[str, str]:
    from sm_contracts.jsonschema import export_all
    from sm_contracts.version import CONTRACTS_VERSION

    out: dict[str, str] = {}
    for name, schema in export_all().items():
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        schema["x-sentinelmesh-contracts-version"] = CONTRACTS_VERSION
        out[name] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return out


def _write(rendered: dict[str, str]) -> None:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in SCHEMA_DIR.glob("*.json")}
    written = set()
    for name, text in rendered.items():
        path = SCHEMA_DIR / f"{name}.json"
        path.write_text(text, encoding="utf-8")
        written.add(path.name)
    for stale in existing - written:
        (SCHEMA_DIR / stale).unlink()
    print(f"wrote {len(written)} JSON Schema file(s) to {SCHEMA_DIR.relative_to(REPO_ROOT)}")


def _check(rendered: dict[str, str]) -> int:
    drift = []
    for name, text in rendered.items():
        path = SCHEMA_DIR / f"{name}.json"
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            drift.append(name)
    committed = {p.stem for p in SCHEMA_DIR.glob("*.json")}
    removed = committed - set(rendered)
    if drift or removed:
        print("JSON Schema is out of date. Run: python scripts/gen_contracts.py")
        for n in sorted(drift):
            print(f"  changed: {n}")
        for n in sorted(removed):
            print(f"  removed: {n}")
        return 1
    print("JSON Schema is up to date.")
    return 0


def _maybe_generate_ts() -> None:
    tool = REPO_ROOT / "packages" / "contracts-ts" / "node_modules" / ".bin"
    j2t = tool / ("json2ts.cmd" if sys.platform == "win32" else "json2ts")
    if not j2t.exists():
        print(
            "TypeScript generation skipped: json-schema-to-typescript not installed.\n"
            "  cd packages/contracts-ts && npm install\n"
            "  then re-run this script."
        )
        return
    TS_DIR.mkdir(parents=True, exist_ok=True)
    for old in TS_DIR.glob("*.ts"):
        old.unlink()

    # One combined `$defs`-only schema -> one file. json2ts emits an interface per
    # def and de-dupes nested shapes, so there are no name collisions and the
    # frontend imports everything from `@sentinelmesh/contracts`.
    defs: dict[str, object] = {}
    for schema_file in sorted(SCHEMA_DIR.glob("*.json")):
        doc = json.loads(schema_file.read_text(encoding="utf-8"))
        for k, v in doc.pop("$defs", {}).items():
            defs.setdefault(k, v)
        for noise in ("x-sentinelmesh-contracts-version", "$schema"):
            doc.pop(noise, None)
        defs[schema_file.stem] = doc

    combined = TS_DIR.parent / "schemas" / "_combined.schema.json"
    combined.write_text(
        json.dumps(
            {"$schema": "https://json-schema.org/draft/2020-12/schema",
             "title": "SentinelMeshContracts", "$defs": defs},
            indent=2, sort_keys=True,
        ),
        encoding="utf-8",
    )
    out_file = TS_DIR / "index.ts"
    subprocess.run(
        [
            str(j2t), "-i", str(combined), "-o", str(out_file),
            "--additionalProperties", "false",
            "--maxItems", "-1",             # keep `T[]`, never expand maxItems into a tuple union
            "--unreachableDefinitions",     # emit every $def, not just what the root references
        ],
        check=True,
    )
    combined.unlink()
    print(f"wrote TypeScript types to {out_file.relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify committed schema is current (CI)")
    args = ap.parse_args()

    rendered = _render_schemas()
    if args.check:
        return _check(rendered)
    _write(rendered)
    _maybe_generate_ts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
