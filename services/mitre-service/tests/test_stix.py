from __future__ import annotations

import json

import pytest
from sm_mitre_service.stix import bundle_sha256, parse_stix_bundle

from .conftest import FIXTURE_BUNDLE


def test_parses_the_fixture_bundle() -> None:
    raw = FIXTURE_BUNDLE.read_bytes()
    parsed = parse_stix_bundle(raw, version="test-1")

    assert {t.tactic_id for t in parsed.tactics} == {"TA0006", "TA0008"}
    techs = {t.technique_id: t for t in parsed.techniques}
    assert set(techs) == {"T1110", "T1110.001", "T1021", "T9999"}

    assert techs["T1110.001"].is_subtechnique
    assert techs["T1110.001"].parent_technique_id == "T1110"
    assert techs["T1110"].tactic_ids == ["TA0006"]
    assert techs["T1021"].tactic_ids == ["TA0008"]
    assert techs["T9999"].deprecated
    assert parsed.subtechnique_count == 1
    assert bundle_sha256(raw) == bundle_sha256(raw)


def test_rejects_a_non_bundle() -> None:
    with pytest.raises(ValueError, match="not a STIX"):
        parse_stix_bundle(b'{"type":"observed-data","objects":[]}', version="x")


def test_rejects_a_bundle_with_no_techniques() -> None:
    empty = json.dumps({"type": "bundle", "objects": [
        {"type": "x-mitre-tactic", "id": "x", "name": "n", "x_mitre_shortname": "s",
         "external_references": [{"source_name": "mitre-attack", "external_id": "TA0006"}]},
    ]}).encode()
    with pytest.raises(ValueError, match="no tactics or no techniques"):
        parse_stix_bundle(empty, version="x")
