"""MITRE ATT&CK contracts (Phase 6; req 7).

The ATT&CK catalog is imported offline from a STIX bundle
(`scripts/import_attack_stix.py`); **no ATT&CK data ships in this repository**.
`mitre-service` never claims coverage beyond the rows actually imported —
`AttackMatrixVersion` records exactly what a run produced, and an unknown
technique id is a typed error, not a guess.

A `TechniqueMapping` links a subject (a detection, later an attack chain) to a
technique with a `confidence`, a `source`, and grounded `evidence`. Rule- and
graph-derived mappings are first-class; an LLM-assisted mapping is allowed but
never authoritative alone (ADR-014).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from .common import SmBaseModel, TenantScoped, TimestampedModel, to_utc
from .detection import EvidenceItem

__all__ = [
    "TECHNIQUE_ID_RE",
    "AttackMatrixVersion",
    "AttackTactic",
    "AttackTechnique",
    "MappingConfidence",
    "MappingSource",
    "MappingSubjectType",
    "TechniqueMapping",
    "TechniqueMatch",
    "is_technique_id",
    "parent_technique_id",
]

# T1110 or T1110.001
TECHNIQUE_ID_RE = re.compile(r"^T\d{4}(\.\d{3})?$")
_TACTIC_ID_RE = re.compile(r"^TA\d{4}$")


def is_technique_id(value: str) -> bool:
    return bool(TECHNIQUE_ID_RE.match(value))


def parent_technique_id(technique_id: str) -> str | None:
    """`"T1110.001"` -> `"T1110"`; `"T1110"` -> `None`."""
    return technique_id.split(".", 1)[0] if "." in technique_id else None


class MappingConfidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class MappingSource(StrEnum):
    rule = "rule"           # a detection rule named the technique
    graph = "graph"         # a graph pattern implied it
    feature = "feature"     # a feature signature implied it
    llm = "llm"             # LLM-assisted (never authoritative alone)
    analyst = "analyst"     # a human set it


class MappingSubjectType(StrEnum):
    detection = "detection"
    attack_chain = "attack_chain"


class AttackTactic(SmBaseModel):
    tactic_id: str = Field(pattern=r"^TA\d{4}$")
    name: str = Field(min_length=1, max_length=128)
    shortname: str = Field(min_length=1, max_length=64, description="STIX x_mitre_shortname.")
    description: str = Field(default="", max_length=8000)
    matrix_version: str = Field(min_length=1, max_length=32)


class AttackTechnique(SmBaseModel):
    technique_id: str = Field(pattern=r"^T\d{4}(\.\d{3})?$")
    name: str = Field(min_length=1, max_length=200)
    tactic_ids: list[str] = Field(default_factory=list, max_length=16)
    description: str = Field(default="", max_length=16000)
    is_subtechnique: bool = False
    parent_technique_id: str | None = Field(default=None, pattern=r"^T\d{4}$")
    matrix_version: str = Field(min_length=1, max_length=32)
    deprecated: bool = False


class AttackMatrixVersion(SmBaseModel):
    """What one import run actually produced. Coverage claims read from here."""

    version: str = Field(min_length=1, max_length=32, description="e.g. '14.1'.")
    source: str = Field(min_length=1, max_length=64, description="e.g. 'mitre/enterprise'.")
    imported_at: datetime
    tactic_count: int = Field(ge=0)
    technique_count: int = Field(ge=0)
    subtechnique_count: int = Field(ge=0)
    stix_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("imported_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class TechniqueMatch(SmBaseModel):
    """One result of the mapping API — a candidate technique for a behaviour."""

    technique_id: str = Field(pattern=r"^T\d{4}(\.\d{3})?$")
    name: str
    tactic_id: str | None = Field(default=None, pattern=r"^TA\d{4}$")
    tactic_name: str | None = None
    confidence: MappingConfidence
    source: MappingSource
    rationale: str = Field(min_length=1, max_length=1000)
    matrix_version: str


class TechniqueMapping(TenantScoped, TimestampedModel):
    """A persisted subject→technique mapping (Postgres `technique_mapping`)."""

    id: UUID
    subject_type: MappingSubjectType
    subject_id: UUID
    technique_id: str = Field(pattern=r"^T\d{4}(\.\d{3})?$")
    tactic_id: str | None = Field(default=None, pattern=r"^TA\d{4}$")
    confidence: MappingConfidence
    source: MappingSource
    rationale: str = Field(min_length=1, max_length=1000)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=64)
    matrix_version: str = Field(min_length=1, max_length=32)
