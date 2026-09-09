"""Parse a MITRE ATT&CK STIX 2.1 bundle into catalog rows.

Only the fields SentinelMesh uses are read. Coverage is exactly what the bundle
contains — the caller records `AttackMatrixVersion` from the returned counts and
the bundle's sha256, and `mitre-service` never claims more.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sm_contracts import AttackTactic, AttackTechnique

__all__ = ["ParsedCatalog", "bundle_sha256", "parse_stix_bundle"]

_ATTACK = "mitre-attack"


@dataclass(frozen=True)
class ParsedCatalog:
    version: str
    source: str
    tactics: list[AttackTactic]
    techniques: list[AttackTechnique]

    @property
    def subtechnique_count(self) -> int:
        return sum(1 for t in self.techniques if t.is_subtechnique)


def bundle_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _external_id(obj: dict[str, Any]) -> str | None:
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == _ATTACK and "external_id" in ref:
            return str(ref["external_id"])
    return None


def parse_stix_bundle(raw: bytes, *, version: str, source: str = "mitre/enterprise") -> ParsedCatalog:
    doc = json.loads(raw)
    if doc.get("type") != "bundle" or not isinstance(doc.get("objects"), list):
        raise ValueError("not a STIX 2.1 bundle")
    objects: list[dict[str, Any]] = doc["objects"]

    shortname_to_ta: dict[str, str] = {}
    tactics: list[AttackTactic] = []
    for o in objects:
        if o.get("type") != "x-mitre-tactic":
            continue
        ta = _external_id(o)
        shortname = o.get("x_mitre_shortname")
        if ta is None or not shortname:
            continue
        shortname_to_ta[shortname] = ta
        tactics.append(AttackTactic(
            tactic_id=ta, name=o["name"], shortname=shortname,
            description=(o.get("description") or "")[:8000], matrix_version=version,
        ))

    # subtechnique-of relationships: source stix id -> parent stix id
    sub_parent: dict[str, str] = {
        r["source_ref"]: r["target_ref"]
        for r in objects
        if r.get("type") == "relationship" and r.get("relationship_type") == "subtechnique-of"
    }
    stixid_to_tid: dict[str, str] = {}
    patterns: list[dict[str, Any]] = []
    for o in objects:
        if o.get("type") != "attack-pattern":
            continue
        tid = _external_id(o)
        if tid is None:
            continue
        stixid_to_tid[o["id"]] = tid
        patterns.append(o)

    techniques: list[AttackTechnique] = []
    for o in patterns:
        tid = stixid_to_tid[o["id"]]
        tactic_ids = sorted({
            shortname_to_ta[p["phase_name"]]
            for p in o.get("kill_chain_phases", [])
            if p.get("kill_chain_name") == _ATTACK and p.get("phase_name") in shortname_to_ta
        })
        parent_sid = sub_parent.get(o["id"])
        parent_tid = stixid_to_tid.get(parent_sid) if parent_sid else None
        techniques.append(AttackTechnique(
            technique_id=tid, name=o["name"], tactic_ids=tactic_ids,
            description=(o.get("description") or "")[:16000],
            is_subtechnique=bool(o.get("x_mitre_is_subtechnique")),
            parent_technique_id=parent_tid, matrix_version=version,
            deprecated=bool(o.get("x_mitre_deprecated") or o.get("revoked")),
        ))

    if not tactics or not techniques:
        raise ValueError("bundle produced no tactics or no techniques")
    return ParsedCatalog(version=version, source=source, tactics=tactics, techniques=techniques)
