"""Rule-based reputation scoring (req 9: reputation scoring is rule-based).

Deterministic: a function of the indicator's confidence, tags and age. No ML, no
external "score" is trusted verbatim — a provider's own score, if any, is a tag,
not the output.
"""

from __future__ import annotations

from sm_contracts import TiConfidence

__all__ = ["reputation_score"]

_CONFIDENCE_BASE: dict[TiConfidence, float] = {
    TiConfidence.low: 0.35,
    TiConfidence.medium: 0.6,
    TiConfidence.high: 0.85,
}

# Tags that raise or lower the score. Lower-cased, substring match.
_MALICIOUS_TAGS = ("malware", "c2", "botnet", "phishing", "ransomware", "exploit", "apt")
_BENIGN_TAGS = ("sinkhole", "parked", "known-good", "allowlist")


def reputation_score(confidence: TiConfidence, tags: list[str]) -> float:
    score = _CONFIDENCE_BASE[confidence]
    lowered = [t.lower() for t in tags]
    if any(any(m in t for m in _MALICIOUS_TAGS) for t in lowered):
        score = min(1.0, score + 0.1)
    if any(any(b in t for b in _BENIGN_TAGS) for t in lowered):
        score = max(0.0, score - 0.3)
    return round(score, 4)
