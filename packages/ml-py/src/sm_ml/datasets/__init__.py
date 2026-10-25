"""Phase 1 modern flow-dataset adapters: CICIDS2017 (corrected release) and
UNSW-NB15. See `scripts/download_datasets.md` for real source URLs and
`sm_ml.datasets.common` for the shared `FlowDataset` shape, leakage-safe
split helpers, and categorical-vocabulary convention (train-split-only,
`__unknown` bucket for the test split) shared with both adapters."""

from __future__ import annotations

from .cicids2017 import DAY_FILES, load_cicids2017
from .common import FlowDataset, LabelledRow, holdout_attack_type, split_indices, train_test_split_rows
from .darpa_tc import ConversionResult, ProvenanceEntity, ProvenanceEvent, convert_cadets_e3_to_parquet
from .darpa_tc_ground_truth import OrthrusAttack, load_orthrus_attack, load_threatrace_labels
from .parquet_convert import convert_cicids2017_to_parquet, convert_unsw_nb15_to_parquet
from .unsw_nb15 import load_unsw_nb15
from .unsw_nb15_official import load_unsw_nb15_official_split

__all__ = [
    "DAY_FILES",
    "ConversionResult",
    "FlowDataset",
    "LabelledRow",
    "OrthrusAttack",
    "ProvenanceEntity",
    "ProvenanceEvent",
    "convert_cadets_e3_to_parquet",
    "convert_cicids2017_to_parquet",
    "convert_unsw_nb15_to_parquet",
    "holdout_attack_type",
    "load_cicids2017",
    "load_orthrus_attack",
    "load_threatrace_labels",
    "load_unsw_nb15",
    "load_unsw_nb15_official_split",
    "split_indices",
    "train_test_split_rows",
]
