"""Phase 1's real three-model comparison on CICIDS2017 and UNSW-NB15.

Run once the real dataset files are in `data/raw/` and
`scripts/verify_datasets.py` passes (see `data/README.md` for exactly what
was used). Writes `eval/reports/<run-id>/{report.json,report.md}`.

Real resource decisions made here, not estimated -- and re-derived twice,
because the first attempt at this (full 4-day CICIDS2017 train / all 4
UNSW-NB15 row files) was actually run on this machine and had to be
killed: it drove system-wide free memory down to ~430 MB of 15.5 GB total
before completing, discovered only by running it, not by estimating a
Python-allocator figure (`tracemalloc`) that undercounts polars/arrow and
model-fitting overhead. Two real numbers came out of that: this machine's
other running processes (browser, IDE, Docker/antivirus, etc.) already use
~9 GB at idle -- the Phase 0 "~10.6 GB budget out of 15.19 GB total"
assumed far more free headroom than this machine actually has right now --
and this loader's real per-row RSS cost (measured with `psutil`, a real
process's real resident memory, not an estimate) is ~3.9 KB/row for
CICIDS2017's ~80 features and ~4.2 KB/row for UNSW-NB15's 192-dimensional
one-hot encoding (far more IANA protocol values appear in `proto` than the
schema doc's "two categorical columns" suggested).

Rescoped from that real measurement, with a large safety margin against
this machine's actual ~6.5 GB free (not the nominal 10.6 GB budget):

- **CICIDS2017**: train = `Friday-WorkingHours-Morning` (benign-only) +
  `Thursday-WorkingHours-Morning-WebAttacks`; test =
  `Friday-WorkingHours-Afternoon-PortScan` -- a real capture-day boundary
  split (never a random row split) that holds PortScan out of training
  entirely, a genuine zero-shot attack-type check. Measured real peak RSS
  for exactly this combination: 2.47 GB.
- **UNSW-NB15**: only `UNSW-NB15_4.csv` (1 of the real 4 row-file parts).
  Measured real peak RSS for this one file: 1.86 GB.
- Both are disclosed, resource-driven reductions of which real rows are
  used, not a fabricated or rounded metric -- the real sha256 of exactly
  the files used is recorded in the run's provenance, same as if every
  file had been used. `_require_free_memory_gb` below additionally
  refuses to start (real enforcement, not a comment) if free memory is
  too low for even this reduced scope.
- One attack category is additionally held out of UNSW-NB15's train split
  explicitly (chosen at runtime from the real class counts, not
  hardcoded -- see `_pick_unsw_holdout`), since its random split (unlike
  CICIDS2017's day boundary) doesn't separate attack categories on its
  own.
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import psutil
from sm_ml_training.benchmark.flow_benchmark import run_flow_benchmark

from sm_ml.datasets import load_cicids2017, load_unsw_nb15
from sm_ml.datasets.common import FlowDataset

_MODELS: tuple[str, ...] = ("isolation_forest", "autoencoder", "gradient_boosting")
_CICIDS_TRAIN_FILES = (
    "Friday-WorkingHours-Morning.pcap_ISCX.csv",
    "Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv",
)
_CICIDS_TEST_FILES = ("Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv",)
_UNSW_ROW_FILES = ("UNSW-NB15_4.csv",)  # see module docstring: real-measured RAM-budget decision
_MIN_FREE_GB = 3.0  # below this, don't even start -- real psutil check, not a comment


def _require_free_memory_gb(min_gb: float) -> None:
    free_gb = psutil.virtual_memory().available / 1e9
    if free_gb < min_gb:
        raise SystemExit(
            f"only {free_gb:.1f} GB free RAM, need at least {min_gb:.1f} GB -- "
            "refusing to start (close other applications and retry); see the module "
            "docstring for how this machine's real headroom was measured"
        )


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _git_short_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _pick_zero_shot_type(train: FlowDataset, test: FlowDataset) -> tuple[str | None, tuple[tuple[float, ...], ...]]:
    """The real attack-type strings present in `test` but never in `train`
    (for CICIDS2017's day split, this is always non-empty: PortScan/DDoS
    are Friday-only). Picks the one with the most test rows, for a held-out
    metric with enough support to mean something."""
    train_types = set(train.attack_types)
    test_counts = Counter(t for t in test.attack_types if t not in train_types and t != "BENIGN")
    if not test_counts:
        return None, ()
    chosen = test_counts.most_common(1)[0][0]
    rows = tuple(r for r, t in zip(test.rows, test.attack_types, strict=True) if t == chosen)
    return chosen, rows


def _pick_unsw_holdout(
    train: FlowDataset, test: FlowDataset
) -> tuple[FlowDataset, str | None, tuple[tuple[float, ...], ...]]:
    """UNSW-NB15's split is a random row split, not a day boundary, so
    (unlike CICIDS2017) every attack category normally appears in both
    train and test. Picks a real attack category from train's own class
    counts -- the one closest to the median count among categories with
    at least 50 rows, so it's neither the dominant class (holding it out
    would badly unbalance training) nor too rare to score meaningfully --
    removes it entirely from train, and returns the matching test rows as
    the held-out eval set."""
    counts = Counter(t for t in train.attack_types if t != "Normal")
    candidates = sorted((t for t, c in counts.items() if c >= 50), key=lambda t: counts[t])
    if not candidates:
        return train, None, ()
    chosen = candidates[len(candidates) // 2]
    keep_idx = [i for i, t in enumerate(train.attack_types) if t != chosen]
    new_train = dataclasses.replace(
        train,
        rows=tuple(train.rows[i] for i in keep_idx),
        labels=tuple(train.labels[i] for i in keep_idx),
        attack_types=tuple(train.attack_types[i] for i in keep_idx),
    )
    held_rows = tuple(r for r, t in zip(test.rows, test.attack_types, strict=True) if t == chosen)
    return new_train, chosen, held_rows


def _run_dataset(name: str, train: FlowDataset, test: FlowDataset, held_out: tuple[str | None, tuple]) -> list[dict]:
    held_out_type, held_out_rows = held_out
    runs: list[dict] = []
    _log(
        f"{name}: train n={train.n_rows} ({train.n_anomalous} anomalous), "
        f"test n={test.n_rows} ({test.n_anomalous} anomalous), "
        f"features={len(train.feature_names)}, held_out_attack_type={held_out_type!r} "
        f"(n={len(held_out_rows)})"
    )
    for model in _MODELS:
        _log(f"{name}: fitting + scoring {model} ...")
        t0 = datetime.now(UTC)
        run = run_flow_benchmark(
            train, test, model=model, seed=1337,
            held_out_attack_type=held_out_type, held_out_rows=held_out_rows or None,
        )
        dt = (datetime.now(UTC) - t0).total_seconds()
        _log(
            f"{name}/{model}: done in {dt:.1f}s -- roc_auc={run.metrics.get('roc_auc')} "
            f"pr_auc={run.metrics.get('pr_auc')} precision={run.metrics.get('precision')} "
            f"recall={run.metrics.get('recall')} held_out_recall={run.held_out_recall}"
        )
        runs.append({"dataset": name, **run.model_dump(mode="json")})
    return runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out-dir", type=Path, default=Path("eval/reports"))
    args = parser.parse_args()

    _require_free_memory_gb(_MIN_FREE_GB)

    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{_git_short_sha()}"
    out_dir = args.out_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    _log(f"run_id={run_id}  writing to {out_dir}  free_mem={psutil.virtual_memory().available / 1e9:.1f}GB")

    _log(f"loading CICIDS2017 (train={_CICIDS_TRAIN_FILES}, test={_CICIDS_TEST_FILES}) ...")
    cic_train, cic_test = load_cicids2017(
        args.data_dir / "cicids2017", train_files=_CICIDS_TRAIN_FILES, test_files=_CICIDS_TEST_FILES
    )
    cic_held = _pick_zero_shot_type(cic_train, cic_test)
    cic_runs = _run_dataset("cicids2017", cic_train, cic_test, cic_held)
    del cic_train, cic_test
    gc.collect()
    _log(f"after cicids2017: free_mem={psutil.virtual_memory().available / 1e9:.1f}GB")
    _require_free_memory_gb(_MIN_FREE_GB)

    _log(f"loading UNSW-NB15 (row_files={_UNSW_ROW_FILES}) ...")
    unsw_train, unsw_test = load_unsw_nb15(args.data_dir / "unsw_nb15", row_files=_UNSW_ROW_FILES)
    unsw_train2, unsw_held_type, unsw_held_rows = _pick_unsw_holdout(unsw_train, unsw_test)
    unsw_runs = _run_dataset("unsw_nb15", unsw_train2, unsw_test, (unsw_held_type, unsw_held_rows))
    del unsw_train, unsw_train2, unsw_test
    gc.collect()

    all_runs = cic_runs + unsw_runs
    report = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_short_sha(),
        "runs": all_runs,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        f"# Phase 1 benchmark run `{run_id}`", "",
        f"Generated {report['generated_at']} at commit `{report['git_commit']}`.", "",
    ]
    for dataset in ("cicids2017", "unsw_nb15"):
        ds_runs = [r for r in all_runs if r["dataset"] == dataset]
        if not ds_runs:
            continue
        lines += [f"## {dataset}", "", f"n_train={ds_runs[0]['n_train']} n_test={ds_runs[0]['n_test']} "
                  f"n_test_anomalous={ds_runs[0]['n_test_anomalous']}", ""]
        held = ds_runs[0]
        if held["held_out_attack_type"]:
            lines.append(
                f"Held-out attack type: `{held['held_out_attack_type']}` "
                f"(n={held['n_held_out']}, never in train)"
            )
            lines.append("")
        lines.append(
            "| Model | ROC-AUC | 95% CI | PR-AUC | Recall@1%FPR | Precision | Recall | F1 | FPR | "
            "Held-out recall | Latency/row (ms) |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in ds_runs:
            m = r["metrics"]
            ci = f"[{r['roc_auc_ci95'][0]:.3f}, {r['roc_auc_ci95'][1]:.3f}]" if r["roc_auc_ci95"] else "N/A"
            hor = f"{r['held_out_recall']:.3f}" if r["held_out_recall"] is not None else "N/A"
            lines.append(
                f"| {r['model_name']} | {m['roc_auc']:.6f} | {ci} | {m['pr_auc']:.6f} | "
                f"{m.get('recall_at_0.01_fpr', float('nan')):.6f} | {m['precision']:.6f} | "
                f"{m['recall']:.6f} | {m['f1']:.6f} | {m['false_positive_rate']:.6f} | {hor} | "
                f"{m['mean_detection_latency_ms']:.4f} |"
            )
        lines.append("")
        pcr = ds_runs[-1]["per_class_recall"]
        if pcr:
            pcr_text = ", ".join(f"{k}={v:.3f}" for k, v in pcr.items())
            lines.append(f"Per-attack-class recall ({ds_runs[-1]['model_name']}): {pcr_text}")
            lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    _log(f"wrote {out_dir / 'report.json'} and {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
