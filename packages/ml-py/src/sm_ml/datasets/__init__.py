"""Phase 1 modern flow-dataset adapters: CICIDS2017 (corrected release) and
UNSW-NB15. See `scripts/download_datasets.md` for real source URLs and
`sm_ml.datasets.common` for the shared `FlowDataset` shape, leakage-safe
split helpers, and categorical-vocabulary convention (train-split-only,
`__unknown` bucket for the test split) shared with both adapters."""

from __future__ import annotations

from .cicids2017 import DAY_FILES, load_cicids2017
from .common import FlowDataset, LabelledRow, holdout_attack_type, split_indices, train_test_split_rows
from .unsw_nb15 import load_unsw_nb15

__all__ = [
    "DAY_FILES",
    "FlowDataset",
    "LabelledRow",
    "holdout_attack_type",
    "load_cicids2017",
    "load_unsw_nb15",
    "split_indices",
    "train_test_split_rows",
]
