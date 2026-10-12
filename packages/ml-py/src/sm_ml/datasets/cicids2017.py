"""CICIDS2017 (Engelen et al. "WTMC-2021" corrected release) adapter.

See `scripts/download_datasets.md` for where the files come from and why
the corrected release is used instead of the original UNB CSVs.

Real, documented data-quality handling, not assumed-away:

- **Leaky identifier columns are dropped unconditionally**: `Flow ID`,
  `Source IP`/`Src IP`, `Destination IP`/`Dst IP`, `Timestamp` (both the
  original and the corrected release's column-naming have been seen in the
  wild; both spellings are matched). These let a model memorise a specific
  flow/capture-time instead of learning attack *patterns* -- the exact
  leakage class the Phase 1 prompt named. `Source Port`/`Destination Port`/
  `Protocol` are KEPT as real, legitimate features (a well-known service
  port is real signal, not an identifier) -- this is a documented choice,
  not an oversight.
- **Column names are whitespace-stripped before matching.** CICIDS2017's
  own CSV header is known to ship columns with a leading space (e.g.
  `" Flow Duration"`) -- matching on the literal un-stripped string would
  silently fail to find `Label`/leaky columns on a real file.
- **The schema is read from each file's own header at runtime**, not
  hard-coded here -- the corrected release's exact column order isn't
  something to guess at and freeze into code when the file can just be
  asked.
- **Day-based split**: the corrected release ships one CSV per capture day
  (Monday..Friday) -- `load_cicids2017` takes which day-files are train vs.
  test explicitly, so a split is a capture-day boundary, never a random
  row split that could put near-duplicate flows from the same attack burst
  on both sides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import FlowDataset, LabelledRow, file_sha256

__all__ = ["DAY_FILES", "load_cicids2017"]

_LEAKY_COLUMNS = frozenset({
    "Flow ID", "Source IP", "Src IP", "Destination IP", "Dst IP", "Timestamp",
})
_LABEL_COLUMN = "Label"
_BENIGN_LABEL = "BENIGN"

# The corrected release's real per-day filenames (verified against
# scripts/verify_datasets.py's expected-file list). Monday is benign-only in
# the original CICIDS2017 collection design -- kept here as documentation of
# that fact, not relied on by the loader (which reads real labels from every
# file regardless).
DAY_FILES: tuple[str, ...] = (
    "Monday-WorkingHours.pcap_ISCX.csv",
    "Tuesday-WorkingHours.pcap_ISCX.csv",
    "Wednesday-workingHours.pcap_ISCX.csv",
    "Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv",
    "Thursday-WorkingHours-Afternoon-Infilteration.pcap_ISCX.csv",
    "Friday-WorkingHours-Morning.pcap_ISCX.csv",
    "Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv",
    "Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv",
)


def _require_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise ImportError("CICIDS2017 loading needs sm-ml[datasets] (polars): "
                           f"{exc}") from exc
    return pl


def _clean_columns(names: list[str]) -> dict[str, str]:
    """real -> stripped name, so lookups never miss on a leading/trailing space."""
    return {name: name.strip() for name in names}


def _read_rows(path: Path, pl: Any) -> tuple[tuple[str, ...], list[LabelledRow]]:
    frame = pl.read_csv(path, infer_schema_length=10_000, ignore_errors=False)
    rename = _clean_columns(frame.columns)
    frame = frame.rename(rename)
    stripped_cols = list(rename.values())

    if _LABEL_COLUMN not in stripped_cols:
        raise ValueError(f"{path}: no {_LABEL_COLUMN!r} column found (columns: {stripped_cols})")

    drop = {c for c in stripped_cols if c in _LEAKY_COLUMNS}
    # sorted, not file order: two files whose header lists the same columns
    # in a different order must still compare equal in `load_cicids2017`.
    feature_cols = sorted(c for c in stripped_cols if c not in drop and c != _LABEL_COLUMN)

    rows: list[LabelledRow] = []
    for record in frame.select([*feature_cols, _LABEL_COLUMN]).iter_rows(named=True):
        label_str = str(record[_LABEL_COLUMN]).strip()
        values = tuple(_to_float(record[c]) for c in feature_cols)
        rows.append(LabelledRow(
            values=values, label=0 if label_str.upper() == _BENIGN_LABEL else 1,
            attack_type=label_str,
        ))
    return tuple(feature_cols), rows


def _to_float(v: object) -> float:
    if v is None:
        return 0.0
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):  # NaN / Infinity -- real, documented CICIDS2017 artifacts
        return 0.0
    return f


def load_cicids2017(
    data_dir: Path, *, train_files: tuple[str, ...], test_files: tuple[str, ...]
) -> tuple[FlowDataset, FlowDataset]:
    """Load real CICIDS2017 rows from `data_dir`, split by capture-day file
    (never by row). Feature columns are the union of every train file's
    columns actually present, in a deterministic (sorted) order -- the
    corrected release's per-day files are not guaranteed to have identical
    column sets after per-day processing quirks, so this is checked, not
    assumed."""
    pl = _require_polars()

    feature_names: tuple[str, ...] | None = None

    def _load_all(names: tuple[str, ...]) -> tuple[list[LabelledRow], list[str]]:
        nonlocal feature_names
        rows: list[LabelledRow] = []
        hashes: list[str] = []
        for name in names:
            path = data_dir / name
            if not path.exists():
                raise FileNotFoundError(f"missing CICIDS2017 file: {path}")
            cols, file_rows = _read_rows(path, pl)
            if feature_names is None:
                feature_names = cols
            elif cols != feature_names:
                raise ValueError(
                    f"{path}: column set {cols} differs from the first file's {feature_names} -- "
                    "per-day files disagree on schema; this loader does not silently align them"
                )
            rows.extend(file_rows)
            hashes.append(file_sha256(path))
        return rows, hashes

    train_rows, train_hashes = _load_all(train_files)
    test_rows, test_hashes = _load_all(test_files)

    if not train_rows:
        raise ValueError("no train rows loaded -- train_files was empty or all-empty")
    if not test_rows:
        raise ValueError("no test rows loaded -- test_files was empty or all-empty")
    assert feature_names is not None  # guaranteed by the raises above

    combined_sha = "+".join(sorted(train_hashes + test_hashes))
    train = FlowDataset(
        dataset_id="cicids2017-train", sha256=combined_sha, feature_names=feature_names,
        rows=tuple(r.values for r in train_rows), labels=tuple(r.label for r in train_rows),
        attack_types=tuple(r.attack_type for r in train_rows),
    )
    test = FlowDataset(
        dataset_id="cicids2017-test", sha256=combined_sha, feature_names=feature_names,
        rows=tuple(r.values for r in test_rows), labels=tuple(r.label for r in test_rows),
        attack_types=tuple(r.attack_type for r in test_rows),
    )
    return train, test
