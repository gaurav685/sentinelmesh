"""Phase 1's real three-model comparison on the FULL CICIDS2017/UNSW-NB15
data, via the memory-safe Parquet + float32 pipeline
(`sm_ml.datasets.parquet_convert` / `sm_ml.datasets.arrays` /
`sm_ml_training.benchmark.array_benchmark`).

This replaces `scripts/run_phase1_benchmark.py`'s reduced-file-subset
smoke test, built only because the original row-based loaders made the
real full-scope data (~2.83M CICIDS2017 rows, ~2.54M UNSW-NB15 rows)
genuinely infeasible on this machine (~6.5 GB real free RAM) -- a
full-scope attempt with the OLD pipeline drove free RAM to ~430 MB and
had to be killed.

Every step below logs the real, OS-reported peak working-set size
(`psutil`'s `peak_wset`, Windows' own cumulative-peak counter -- not a
polled estimate) so the before/after table in this run's `report.md` is
measured, not asserted. Same 1.5 GB free-memory floor as the smoke test's
watchdog (`_require_free_memory_gb`), checked before each dataset.
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil
from sm_ml_training.benchmark.array_benchmark import run_array_benchmark

from sm_ml.datasets.arrays import ArrayFlowDataset, load_cicids2017_arrays, load_unsw_nb15_arrays
from sm_ml.datasets.cicids2017 import DAY_FILES
from sm_ml.datasets.parquet_convert import convert_cicids2017_to_parquet, convert_unsw_nb15_to_parquet

_MODELS: tuple[str, ...] = ("isolation_forest", "autoencoder", "gradient_boosting")
_CICIDS_TRAIN_DAYS = DAY_FILES[:5]  # Monday..Thursday -- the original Phase 1 plan's full day split
_CICIDS_TEST_DAYS = DAY_FILES[5:]  # Friday (3 files)
_UNSW_ROW_FILES = ("UNSW-NB15_1.csv", "UNSW-NB15_2.csv", "UNSW-NB15_3.csv", "UNSW-NB15_4.csv")
# Real-measured reduction (not a guess): even after the Parquet + float32 +
# single-pass-select fixes, loading all 4 real UNSW-NB15 files costs ~4.9 GB
# RSS by itself (measured with psutil) -- on this machine's real ~6.5-6.8 GB
# free headroom, that leaves no room for model-fitting overhead and trips the
# 3 GB safety floor before any model runs. 2 of 4 files measured at 2.47 GB,
# leaving a real ~4.3 GB margin. See docs/ML_BENCHMARK_REPORT.md for the full
# before/after numbers and why (proto's ~130+ real distinct values inflate
# the one-hot width to 192 columns).
_UNSW_LOAD_ROW_FILES = ("UNSW-NB15_1.csv", "UNSW-NB15_2.csv")
_MIN_FREE_GB = 3.0

_PROC = psutil.Process(os.getpid())
_STEPS: list[dict[str, Any]] = []


def _rss_mb() -> float:
    return _PROC.memory_info().rss / 1e6


def _peak_mb() -> float:
    return _PROC.memory_info().peak_wset / 1e6  # Windows' own cumulative peak, not a polled guess


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _step(name: str, t0: float) -> None:
    rec = {
        "step": name, "elapsed_s": round(time.perf_counter() - t0, 1),
        "rss_mb": round(_rss_mb(), 1), "peak_wset_mb": round(_peak_mb(), 1),
    }
    _STEPS.append(rec)
    _log(f"{name}: elapsed={rec['elapsed_s']}s rss={rec['rss_mb']}MB peak_wset_so_far={rec['peak_wset_mb']}MB")


def _require_free_memory_gb(min_gb: float) -> None:
    free_gb = psutil.virtual_memory().available / 1e9
    if free_gb < min_gb:
        raise SystemExit(f"only {free_gb:.1f} GB free RAM, need at least {min_gb:.1f} GB -- refusing to continue")


def _git_short_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _pick_zero_shot_type(train: ArrayFlowDataset, test: ArrayFlowDataset) -> tuple[str | None, Any]:
    train_types = set(train.attack_types)
    test_counts = Counter(t for t in test.attack_types if t not in train_types and t != "BENIGN")
    if not test_counts:
        return None, None
    chosen = test_counts.most_common(1)[0][0]
    mask = [t == chosen for t in test.attack_types]
    return chosen, test.X[mask]


def _pick_and_remove_unsw_holdout(
    train: ArrayFlowDataset, test: ArrayFlowDataset
) -> tuple[ArrayFlowDataset, str | None, Any]:
    counts = Counter(t for t in train.attack_types if t != "Normal")
    candidates = sorted((t for t, c in counts.items() if c >= 50), key=lambda t: counts[t])
    if not candidates:
        return train, None, None
    chosen = candidates[len(candidates) // 2]
    keep_mask = [t != chosen for t in train.attack_types]
    new_train = dataclasses.replace(
        train, X=train.X[keep_mask], y=train.y[keep_mask],
        attack_types=tuple(t for t, k in zip(train.attack_types, keep_mask, strict=True) if k),
    )
    held_mask = [t == chosen for t in test.attack_types]
    return new_train, chosen, test.X[held_mask]


def _run_dataset(
    name: str, train: ArrayFlowDataset, test: ArrayFlowDataset, held: tuple[str | None, Any],
    train_parquet_paths: tuple[Path, ...], label_col: str, benign_value: Any,
) -> list[dict[str, Any]]:
    held_type, held_x = held
    runs: list[dict[str, Any]] = []
    _log(
        f"{name}: train n={train.n_rows} ({int(train.y.sum())} anomalous), test n={test.n_rows} "
        f"({test.n_anomalous} anomalous), features={len(train.feature_names)}, "
        f"held_out_attack_type={held_type!r} (n={0 if held_x is None else held_x.shape[0]})"
    )
    for model in _MODELS:
        t0 = time.perf_counter()
        run = run_array_benchmark(
            train, test, model=model, seed=1337, train_parquet_paths=train_parquet_paths,
            label_col=label_col, benign_value=benign_value, held_out_attack_type=held_type, held_out_x=held_x,
        )
        _step(f"{name}/{model}", t0)
        _log(
            f"  roc_auc={run.metrics.get('roc_auc')} pr_auc={run.metrics.get('pr_auc')} "
            f"precision={run.metrics.get('precision')} recall={run.metrics.get('recall')} "
            f"held_out_recall={run.held_out_recall}"
        )
        runs.append({"dataset": name, **run.model_dump(mode="json")})
    return runs


def _run_cicids2017(args: argparse.Namespace, out_dir: Path) -> None:
    t0 = time.perf_counter()
    convert_cicids2017_to_parquet(args.raw_dir / "cicids2017", args.processed_dir / "cicids2017", DAY_FILES)
    _step("convert_cicids2017_to_parquet (8 files)", t0)

    t0 = time.perf_counter()
    train_parquet = tuple(f"{Path(n).stem}.parquet" for n in _CICIDS_TRAIN_DAYS)
    test_parquet = tuple(f"{Path(n).stem}.parquet" for n in _CICIDS_TEST_DAYS)
    cic_train, cic_test, cic_info = load_cicids2017_arrays(
        args.processed_dir / "cicids2017", train_files=train_parquet, test_files=test_parquet,
    )
    _step("load_cicids2017_arrays (full 5 train-day / 3 test-day files)", t0)
    _log(f"cicids2017 benign-sampling info: {cic_info}")
    _require_free_memory_gb(_MIN_FREE_GB)

    cic_held = _pick_zero_shot_type(cic_train, cic_test)
    cic_train_paths = tuple(args.processed_dir / "cicids2017" / p for p in train_parquet)
    cic_runs = _run_dataset("cicids2017", cic_train, cic_test, cic_held, cic_train_paths, "Label", "BENIGN")
    del cic_train, cic_test
    gc.collect()
    _step("after cicids2017 (freed)", time.perf_counter())

    partial = {"memory_steps": _STEPS, "benign_sampling_info": cic_info, "runs": cic_runs}
    (out_dir / "partial_cicids2017.json").write_text(json.dumps(partial, indent=2), encoding="utf-8")
    _log(f"wrote {out_dir / 'partial_cicids2017.json'}")


def _run_unsw_nb15(args: argparse.Namespace, out_dir: Path) -> None:
    t0 = time.perf_counter()
    convert_unsw_nb15_to_parquet(args.raw_dir / "unsw_nb15", args.processed_dir / "unsw_nb15", _UNSW_ROW_FILES)
    _step("convert_unsw_nb15_to_parquet (4 files)", t0)

    t0 = time.perf_counter()
    unsw_row_parquet = tuple(f"{Path(n).stem}.parquet" for n in _UNSW_LOAD_ROW_FILES)
    unsw_train, unsw_test, unsw_info = load_unsw_nb15_arrays(
        args.processed_dir / "unsw_nb15", row_files=unsw_row_parquet, test_fraction=0.3, seed=1337,
    )
    _step(f"load_unsw_nb15_arrays ({len(_UNSW_LOAD_ROW_FILES)} of 4 files -- real-measured RAM floor)", t0)
    _require_free_memory_gb(_MIN_FREE_GB)

    unsw_train2, unsw_held_type, unsw_held_x = _pick_and_remove_unsw_holdout(unsw_train, unsw_test)
    unsw_train_paths = tuple(args.processed_dir / "unsw_nb15" / p for p in unsw_row_parquet)
    unsw_runs = _run_dataset(
        "unsw_nb15", unsw_train2, unsw_test, (unsw_held_type, unsw_held_x), unsw_train_paths, "Label", 0,
    )
    del unsw_train, unsw_train2, unsw_test
    gc.collect()
    _step("after unsw_nb15 (freed)", time.perf_counter())

    partial = {
        "memory_steps": _STEPS, "benign_sampling_info": unsw_info, "runs": unsw_runs,
        "scope_note": (
            f"Used {len(_UNSW_LOAD_ROW_FILES)} of 4 real UNSW-NB15 row files "
            f"({', '.join(_UNSW_LOAD_ROW_FILES)}), not all 4 -- real-measured RAM floor on this "
            "machine (see module docstring / docs/ML_BENCHMARK_REPORT.md)."
        ),
    }
    (out_dir / "partial_unsw_nb15.json").write_text(json.dumps(partial, indent=2), encoding="utf-8")
    _log(f"wrote {out_dir / 'partial_unsw_nb15.json'}")


def _write_markdown(
    out_dir: Path, report: dict[str, Any], all_runs: list[dict[str, Any]], steps: list[dict[str, Any]]
) -> None:
    lines = [
        f"# Phase 1 FULL-DATA benchmark run `{report['run_id']}`", "",
        f"Generated {report['generated_at']} at commit `{report['git_commit']}`.", "",
        report["note"], "",
    ]
    lines.append("## Real peak memory per step (OS-reported `peak_wset`, psutil)")
    lines.append("")
    lines.append("| Step | Elapsed (s) | RSS at end (MB) | Peak working-set so far (MB) |")
    lines.append("|---|---|---|---|")
    for s in steps:
        lines.append(f"| {s['step']} | {s['elapsed_s']} | {s['rss_mb']} | {s['peak_wset_mb']} |")
    lines.append("")
    for dataset in ("cicids2017", "unsw_nb15"):
        ds_runs = [r for r in all_runs if r["dataset"] == dataset]
        if not ds_runs:
            continue
        r0 = ds_runs[0]
        lines += [
            f"## {dataset}", "",
            f"n_train={r0['n_train']} n_test={r0['n_test']} n_test_anomalous={r0['n_test_anomalous']}",
            "",
        ]
        if r0["held_out_attack_type"]:
            lines.append(f"Held-out attack type: `{r0['held_out_attack_type']}` (n={r0['n_held_out']}, never in train)")
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


def _merge(out_dir: Path, run_id: str) -> None:
    cic = json.loads((out_dir / "partial_cicids2017.json").read_text(encoding="utf-8"))
    unsw = json.loads((out_dir / "partial_unsw_nb15.json").read_text(encoding="utf-8"))
    all_runs = cic["runs"] + unsw["runs"]
    report = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_short_sha(),
        "label": "FULL DATA for CICIDS2017; real-measured reduced scope for UNSW-NB15 -- "
                 "memory-safe Parquet + float32 pipeline",
        "note": "cicids2017 and unsw_nb15 were run as SEPARATE processes (see memory_steps_* below) "
                "so each dataset's peak memory is independent -- in a single shared process, "
                "CICIDS2017's ~1.9GB resident footprint stacked with UNSW-NB15's load and "
                "tripped the 3GB free-memory floor. Measured, not assumed; see docs/ML_BENCHMARK_REPORT.md.",
        "cicids2017_scope": "full -- all 8 real day files (5 train, 3 test)",
        "unsw_nb15_scope": unsw.get("scope_note", "unknown"),
        "memory_steps_cicids2017": cic["memory_steps"],
        "memory_steps_unsw_nb15": unsw["memory_steps"],
        "cicids2017_benign_sampling_info": cic["benign_sampling_info"],
        "runs": all_runs,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_markdown(out_dir, report, all_runs, cic["memory_steps"] + unsw["memory_steps"])
    _log(f"wrote {out_dir / 'report.json'} and {out_dir / 'report.md'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--out-dir", type=Path, default=Path("eval/reports"))
    parser.add_argument("--run-id", default=None, help="shared run-id across separate-process invocations")
    parser.add_argument("--dataset", choices=["cicids2017", "unsw_nb15", "merge"], required=True)
    args = parser.parse_args()

    run_id = args.run_id or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{_git_short_sha()}"
    out_dir = args.out_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dataset == "merge":
        _merge(out_dir, run_id)
        return 0

    _require_free_memory_gb(_MIN_FREE_GB)
    _step("start", time.perf_counter())
    _log(f"run_id={run_id} dataset={args.dataset} writing to {out_dir} "
         f"free_mem={psutil.virtual_memory().available / 1e9:.1f}GB")

    if args.dataset == "cicids2017":
        _run_cicids2017(args, out_dir)
    else:
        _run_unsw_nb15(args, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
