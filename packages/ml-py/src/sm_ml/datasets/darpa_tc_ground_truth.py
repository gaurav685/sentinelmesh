"""CADETS E3 ground-truth label loading -- two real, independently-derived
label sets, both already secured and committed at `data/ground_truth/cadets_e3/`
(see `data/README.md`'s "Phase 2: DARPA TC CADETS E3" section for full
provenance/citations). Deliberately kept as two SEPARATE label sets, never
merged into one, because they answer different questions at different
granularity:

- **ThreaTrace** (`threatrace_node_labels.txt`): a flat list of node UUIDs
  covering the whole attack *neighbourhood* -- node-level evaluation.
- **Orthrus** (`node_Nginx_Backdoor_{06,11,12,13}.csv`): the precise
  attack-chain nodes for each of 4 real attack attempts, each with its own
  real timestamp window -- used for the time-window-level evaluation
  KAIROS's own published methodology uses, reported separately per the
  user's explicit instruction not to collapse the two granularities.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ORTHRUS_ATTACK_WINDOWS",
    "OrthrusAttack",
    "load_orthrus_attack",
    "load_threatrace_labels",
]

# Real per-attack time windows, US/Eastern, for the CADETS_E3 "Nginx_Backdoor"
# scenario -- read directly from `ubc-provenance/PIDSMaker`'s own
# `pidsmaker/config/config.py` `CADETS_E3` dataset entry (Apache-2.0), not
# re-derived or guessed. `used_in_pidsmaker_results` records whether that
# repo's own reported numbers include this attack (file 11 is excluded
# there); kept available here regardless, inclusion is this project's own
# call once real detection behaviour on it is seen.
ORTHRUS_ATTACK_WINDOWS: dict[str, tuple[str, str, bool]] = {
    "node_Nginx_Backdoor_06.csv": ("2018-04-06 11:20:00", "2018-04-06 12:09:00", True),
    "node_Nginx_Backdoor_11.csv": ("2018-04-11 15:07:00", "2018-04-11 15:16:00", False),
    "node_Nginx_Backdoor_12.csv": ("2018-04-12 13:59:00", "2018-04-12 14:39:00", True),
    "node_Nginx_Backdoor_13.csv": ("2018-04-13 09:03:00", "2018-04-13 09:16:00", True),
}


@dataclass(frozen=True)
class OrthrusAttack:
    file_name: str
    node_uuids: frozenset[str]
    window_start: str  # "YYYY-MM-DD HH:MM:SS", US/Eastern, real DARPA engagement time
    window_end: str
    used_in_pidsmaker_results: bool


def load_threatrace_labels(path: Path) -> frozenset[str]:
    """Real ThreaTrace node-level ground truth: one UUID per line, real
    duplicates present in the upstream file (same UUID can repeat) --
    deduplicated here, same as PIDSMaker's own loader does."""
    uuids: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                uuids.add(line)
    return frozenset(uuids)


def load_orthrus_attack(path: Path) -> OrthrusAttack:
    """Real Orthrus per-attack ground truth: CSV rows of
    `uuid,{'<entity_type>': '<label>'},timestamp_ns` -- only the first
    column (the real node UUID) is used; the dict/timestamp columns are the
    node's own type/label and a real CDM timestamp, kept available in the
    raw file but not needed for node-set membership."""
    uuids: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if row and row[0].strip():
                uuids.add(row[0].strip())
    window = ORTHRUS_ATTACK_WINDOWS.get(path.name)
    if window is None:
        raise ValueError(
            f"{path.name}: no real attack window recorded for this file -- "
            f"known files: {sorted(ORTHRUS_ATTACK_WINDOWS)}"
        )
    start, end, used = window
    return OrthrusAttack(
        file_name=path.name, node_uuids=frozenset(uuids), window_start=start, window_end=end,
        used_in_pidsmaker_results=used,
    )
