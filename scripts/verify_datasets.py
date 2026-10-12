#!/usr/bin/env python3
"""Verify the Phase 1 modern-flow datasets are present and record real
evidence about them (sha256, row count, byte size) -- never assumes a
download succeeded just because a path exists.

    python scripts/verify_datasets.py
    python scripts/verify_datasets.py --dataset cicids2017

Exits non-zero with a specific, actionable message if any expected file is
missing -- never silently skips a dataset. Exact source URLs and where to
place each file: scripts/download_datasets.md.

Row counts are real (every line counted, not estimated from file size) but
read in fixed-size chunks so a multi-GB CSV never has to be loaded whole
into memory -- this script has no reason to need more than a few MB of RAM
regardless of dataset size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = REPO_ROOT / "data" / "raw"
METADATA_ROOT = REPO_ROOT / "data" / "metadata"

_CHUNK_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ExpectedFile:
    name: str
    required: bool = True
    note: str = ""


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    dir_name: str
    files: tuple[ExpectedFile, ...]


DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        key="cicids2017",
        dir_name="cicids2017",
        files=(
            # Real correction: these are the Kaggle mirror's ORIGINAL
            # (uncorrected) 2017 labels, not the WTMC-2021 corrected release
            # -- see data/README.md. The real corrected release is the
            # separate "cicids2017_corrected" entry below.
            ExpectedFile("Monday-WorkingHours.pcap_ISCX.csv"),
            ExpectedFile("Tuesday-WorkingHours.pcap_ISCX.csv"),
            ExpectedFile("Wednesday-workingHours.pcap_ISCX.csv"),
            ExpectedFile("Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv"),
            ExpectedFile("Thursday-WorkingHours-Afternoon-Infilteration.pcap_ISCX.csv"),
            ExpectedFile("Friday-WorkingHours-Morning.pcap_ISCX.csv"),
            ExpectedFile("Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv"),
            ExpectedFile("Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv"),
        ),
    ),
    DatasetSpec(
        key="cicids2017_corrected",
        dir_name="cicids2017_corrected",
        files=(
            # The REAL WTMC-2021 corrected release (Engelen, Rimmer, Joosen),
            # downloaded and unzipped this session -- 5 real files, one per
            # capture day (no morning/afternoon split, unlike the Kaggle
            # mirror's 8-file layout above), no "pcap_ISCX" suffix. Exact
            # names confirmed from the real unzipped archive, not guessed.
            ExpectedFile("Monday-WorkingHours.csv"),
            ExpectedFile("Tuesday-WorkingHours.csv"),
            ExpectedFile("Wednesday-WorkingHours.csv"),
            ExpectedFile("Thursday-WorkingHours.csv"),
            ExpectedFile("Friday-WorkingHours.csv"),
        ),
    ),
    DatasetSpec(
        key="unsw_nb15",
        dir_name="unsw_nb15",
        files=(
            ExpectedFile("UNSW-NB15_1.csv"),
            ExpectedFile("UNSW-NB15_2.csv"),
            ExpectedFile("UNSW-NB15_3.csv"),
            ExpectedFile("UNSW-NB15_4.csv"),
            ExpectedFile("UNSW-NB15_features.csv", note="column names -- the 4 row files above have no header"),
            ExpectedFile("UNSW_NB15_training-set.csv", required=False, note="authors' own split; sanity check only"),
            ExpectedFile("UNSW_NB15_testing-set.csv", required=False, note="authors' own split; sanity check only"),
        ),
    ),
)


@dataclass
class FileReport:
    name: str
    present: bool
    required: bool
    sha256: str | None = None
    size_bytes: int | None = None
    row_count: int | None = None
    note: str = ""


@dataclass
class DatasetReport:
    key: str
    checked_at: str
    files: list[FileReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(f.present for f in self.files if f.required)


def _sha256_and_lines(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    lines = 0
    with path.open("rb") as fh:
        tail_had_newline = True
        while True:
            chunk = fh.read(_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            lines += chunk.count(b"\n")
            tail_had_newline = chunk.endswith(b"\n")
        if not tail_had_newline and lines >= 0:
            lines += 1  # a final line with no trailing newline still counts
    return digest.hexdigest(), lines


def verify_one(spec: DatasetSpec) -> DatasetReport:
    report = DatasetReport(key=spec.key, checked_at=datetime.now(UTC).isoformat())
    base = RAW_ROOT / spec.dir_name
    for expected in spec.files:
        path = base / expected.name
        if not path.exists():
            report.files.append(FileReport(
                name=expected.name, present=False, required=expected.required, note=expected.note,
            ))
            continue
        sha, lines = _sha256_and_lines(path)
        report.files.append(FileReport(
            name=expected.name, present=True, required=expected.required,
            sha256=sha, size_bytes=path.stat().st_size, row_count=lines, note=expected.note,
        ))
    return report


def _print_report(report: DatasetReport) -> None:
    print(f"\n=== {report.key} ===")
    for f in report.files:
        if not f.present:
            marker = "MISSING (required)" if f.required else "missing (optional)"
            print(f"  [{marker}] {f.name}" + (f"  -- {f.note}" if f.note else ""))
            continue
        mb = (f.size_bytes or 0) / (1024 * 1024)
        print(f"  [ok] {f.name}  {mb:.1f} MB  {f.row_count} lines  sha256={f.sha256}")
    print(f"  status: {'OK' if report.ok else 'INCOMPLETE -- see MISSING (required) above'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", choices=[d.key for d in DATASETS], default=None,
                     help="Verify only this dataset (default: both)")
    args = ap.parse_args()

    specs = [d for d in DATASETS if args.dataset is None or d.key == args.dataset]
    METADATA_ROOT.mkdir(parents=True, exist_ok=True)

    all_ok = True
    for spec in specs:
        report = verify_one(spec)
        _print_report(report)
        all_ok = all_ok and report.ok
        out_path = METADATA_ROOT / f"{spec.key}.json"
        out_path.write_text(
            json.dumps(
                {
                    "dataset": report.key,
                    "checked_at": report.checked_at,
                    "files": [
                        {
                            "name": f.name, "present": f.present, "required": f.required,
                            "sha256": f.sha256, "size_bytes": f.size_bytes, "row_count": f.row_count,
                            "note": f.note,
                        }
                        for f in report.files
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  wrote {out_path}")

    if not all_ok:
        print(
            "\nOne or more required files are missing. See scripts/download_datasets.md "
            "for exact source URLs and where to place each file.",
            file=sys.stderr,
        )
        return 1
    print("\nAll required files present and verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
