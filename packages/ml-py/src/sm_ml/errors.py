"""Model failure types. `detection-engine` turns any of these into
`scoring_status = DEGRADED` (ADR-013) — never a dropped detection."""

from __future__ import annotations

__all__ = ["ModelError", "ModelNotTrained", "ModelUnavailable"]


class ModelError(RuntimeError):
    """Base for every model failure."""


class ModelUnavailable(ModelError):
    """The model could not be loaded — no artifact, or a serving dependency
    (numpy / scikit-learn) is not installed. `ml-inference` returns the typed
    code `MODEL_UNAVAILABLE`."""


class ModelNotTrained(ModelError):
    """The model interface exists but has no trained weights (e.g. the
    autoencoder before a training run)."""
