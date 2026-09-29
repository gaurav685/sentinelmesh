"""Real-dataset ingestion contracts (Phase 18 follow-up).

An authenticated analyst can upload a real, public, labelled dataset file
through the SOC UI and replay it through the real ingestion pipeline --
distinct from `simulation-service`'s synthetic scenarios (Phase 12) and
from a real sensor's own `POST /api/v1/ingest/*` (a different trust
boundary: a logged-in, permission-checked analyst, not a device
credential). Only the NSL-KDD network-connection format is understood;
an unrecognized format is refused, never guessed at.
"""

from __future__ import annotations

from pydantic import Field

from ..common import SmBaseModel

__all__ = ["DatasetUploadResult"]


class DatasetUploadResult(SmBaseModel):
    dataset: str = Field(description="Which real, public dataset this was parsed as, e.g. 'nsl-kdd'.")
    rows_read: int = Field(ge=0)
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    #: The dataset's own labels (e.g. "normal", "neptune") and how many rows
    #: carried each -- never sent to the pipeline itself, only reported back
    #: so the person who uploaded it can compare it against what the
    #: detection pipeline actually decides.
    ground_truth_labels: dict[str, int] = Field(default_factory=dict)
    sensor_id: str = Field(description="The per-tenant sensor row this upload's events were attributed to.")
