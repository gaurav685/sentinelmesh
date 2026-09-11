"""Threat-memory contracts (Phase 13).

`services/memory-service` owns three tenant-scoped record kinds — behavioral
patterns, campaigns (groups of related attack chains), and adversary
fingerprints (one per subject, evolving as it reappears). None of these
duplicate the operational attack graph (`graph-service`, Neo4j) or the
detection/chain tables (`detection-engine` / `correlation-engine`, Postgres) —
see `docs/ARCHITECTURE_DECISIONS.md` ADR-011. The similarity feature vector
itself is never exposed over the API; only the similarity score is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from ..common import SmBaseModel, TenantScoped, TimestampedModel, to_utc
from ..enums import ThreatSubjectType

__all__ = [
    "AdversaryFingerprint",
    "Campaign",
    "CampaignStatus",
    "MemoryPatternKind",
    "SimilarityMatch",
    "ThreatMemory",
]

#: A closed, additive set — a new pattern kind is a new literal value, never a
#: free-text column (Constitution §10).
MemoryPatternKind = Literal["technique_sequence"]
CampaignStatus = Literal["active", "dormant", "closed"]


class ThreatMemory(TenantScoped, TimestampedModel):
    """A behavioral pattern observed for one subject — upserted as the
    subject's technique set grows, never duplicated per occurrence."""

    id: UUID
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    pattern_kind: MemoryPatternKind
    technique_ids: list[str] = Field(default_factory=list, max_length=200)
    occurrence_count: int = Field(ge=1)
    first_seen: datetime
    last_seen: datetime
    #: Where this pattern came from — e.g. `"attack_chain:<uuid>"`. Never a
    #: fabricated source; always traceable back to a real detection or chain.
    source: str = Field(min_length=1, max_length=256)

    @field_validator("first_seen", "last_seen")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class Campaign(TenantScoped, TimestampedModel):
    """A set of attack chains judged related by shared technique usage —
    threat memory's cross-incident view."""

    id: UUID
    status: CampaignStatus
    chain_ids: list[str] = Field(default_factory=list, max_length=500)
    technique_ids: list[str] = Field(default_factory=list, max_length=200)
    first_seen: datetime
    last_seen: datetime

    @field_validator("first_seen", "last_seen")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class AdversaryFingerprint(TenantScoped, TimestampedModel):
    """One evolving fingerprint per subject — the "has this been seen
    before" record `campaign_ids` links back to."""

    id: UUID
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    technique_ids: list[str] = Field(default_factory=list, max_length=200)
    campaign_ids: list[str] = Field(default_factory=list, max_length=200)
    first_seen: datetime
    last_seen: datetime

    @field_validator("first_seen", "last_seen")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class SimilarityMatch(SmBaseModel):
    """One result of a similarity search — the record plus its score. The
    underlying feature vector is never returned."""

    kind: Literal["threat_memory", "campaign", "adversary_fingerprint"]
    id: UUID
    #: Cosine similarity to the query vector, `[-1, 1]` in principle but
    #: `[0, 1]` in practice for L2-normalized, non-negative count vectors.
    score: float = Field(ge=-1.0, le=1.0)
    technique_ids: list[str] = Field(default_factory=list, max_length=200)
    last_seen: datetime
    #: True when the match came from an exact-match fallback (pgvector
    #: unavailable) rather than an index-backed nearest-neighbor search —
    #: the result is still real, just found a different way.
    exact_fallback: bool = False

    @field_validator("last_seen")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)
