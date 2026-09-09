from __future__ import annotations

from sm_ti_service.reputation import reputation_score

from sm_contracts import TiConfidence


def test_confidence_sets_the_base() -> None:
    assert reputation_score(TiConfidence.low, []) < reputation_score(TiConfidence.high, [])


def test_malicious_tags_raise_benign_tags_lower() -> None:
    base = reputation_score(TiConfidence.medium, [])
    assert reputation_score(TiConfidence.medium, ["malware-c2"]) > base
    assert reputation_score(TiConfidence.medium, ["sinkhole"]) < base


def test_score_stays_in_unit_interval() -> None:
    assert 0.0 <= reputation_score(TiConfidence.high, ["c2", "apt", "ransomware"]) <= 1.0
    assert 0.0 <= reputation_score(TiConfidence.low, ["known-good", "parked"]) <= 1.0


def test_is_deterministic() -> None:
    a = reputation_score(TiConfidence.medium, ["phishing"])
    b = reputation_score(TiConfidence.medium, ["phishing"])
    assert a == b
