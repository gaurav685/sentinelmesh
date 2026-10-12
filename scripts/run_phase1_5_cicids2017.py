"""Phase 1.5 CICIDS2017 reruns: the Mon-Thu/Fri day split (relabelled
"unseen-attack generalisation", now with the fixed autoencoder and
validation-calibrated thresholds) AND the new within-day "known-attack"
split, side by side. Writes eval/reports/<run-id>/partial_cicids2017.json
(same shape run_phase1_benchmark_full.py's merge step expects)."""

from __future__ import annotations

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

from sm_ml.datasets.arrays import load_cicids2017_arrays, load_cicids2017_known_attack_split
from sm_ml.datasets.cicids2017 import DAY_FILES
from sm_ml.datasets.parquet_convert import convert_cicids2017_to_parquet

_MODELS = ("isolation_forest", "autoencoder", "gradient_boosting")
_PROC = psutil.Process(os.getpid())
_STEPS: list[dict[str, Any]] = []


def _log(msg: str) -> None:
    print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


def _step(name: str, t0: float) -> None:
    rec = {
        "step": name, "elapsed_s": round(time.perf_counter() - t0, 1),
        "rss_mb": round(_PROC.memory_info().rss / 1e6, 1),
        "peak_wset_mb": round(_PROC.memory_info().peak_wset / 1e6, 1),
    }
    _STEPS.append(rec)
    _log(f"{name}: elapsed={rec['elapsed_s']}s rss={rec['rss_mb']}MB peak_wset_so_far={rec['peak_wset_mb']}MB")


def _git_short_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=5, check=False,
    )
    return out.stdout.strip() or "unknown"


def _pick_zero_shot_type(train: Any, test: Any) -> tuple[str | None, Any]:
    train_types = set(train.attack_types)
    test_counts = Counter(t for t in test.attack_types if t not in train_types and t != "BENIGN")
    if not test_counts:
        return None, None
    chosen = test_counts.most_common(1)[0][0]
    mask = [t == chosen for t in test.attack_types]
    return chosen, test.X[mask]


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{_git_short_sha()}"
    out_dir = Path("eval/reports") / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    _log(f"run_id={run_id} free_mem={psutil.virtual_memory().available / 1e9:.1f}GB")

    raw_dir = Path("data/raw/cicids2017")
    processed_dir = Path("data/processed/cicids2017")

    t0 = time.perf_counter()
    convert_cicids2017_to_parquet(raw_dir, processed_dir, DAY_FILES)
    _step("convert_cicids2017_to_parquet (8 files)", t0)

    # --- 1. day split, relabelled "unseen-attack generalisation" ---
    train_days = DAY_FILES[:5]
    test_days = DAY_FILES[5:]
    train_parquet = tuple(f"{Path(n).stem}.parquet" for n in train_days)
    test_parquet = tuple(f"{Path(n).stem}.parquet" for n in test_days)

    t0 = time.perf_counter()
    day_train, day_test, day_info = load_cicids2017_arrays(
        processed_dir, train_files=train_parquet, test_files=test_parquet,
    )
    _step("load_cicids2017_arrays (day split)", t0)
    day_held_type, day_held_x = _pick_zero_shot_type(day_train, day_test)
    day_train_paths = tuple(processed_dir / p for p in train_parquet)

    day_runs = {}
    for model in _MODELS:
        t0 = time.perf_counter()
        run = run_array_benchmark(
            day_train, day_test, model=model, seed=1337, train_parquet_paths=day_train_paths,
            held_out_attack_type=day_held_type, held_out_x=day_held_x, calibrate_at_fpr=0.01,
        )
        _step(f"day_split/{model}", t0)
        day_runs[model] = run.model_dump(mode="json")
        _log(
            f"  {model}: roc_auc={run.metrics.get('roc_auc')} "
            f"recall@cal={run.metrics.get('recall_at_calibrated_threshold')} "
            f"held_out_recall={run.held_out_recall}"
        )
    del day_train, day_test
    gc.collect()
    _step("after day_split (freed)", time.perf_counter())

    # --- 2. known-attack split (within-day, time-window-grouped) ---
    t0 = time.perf_counter()
    all_parquet = tuple(f"{Path(n).stem}.parquet" for n in DAY_FILES)
    ka_train, ka_test, ka_info = load_cicids2017_known_attack_split(
        processed_dir, files=all_parquet, test_fraction=0.3, window_rows=2000, seed=1337,
    )
    _step("load_cicids2017_known_attack_split", t0)
    _log(f"known-attack split info: {ka_info}")
    ka_train_full_parquet = tuple(processed_dir / p for p in all_parquet)

    ka_runs = {}
    for model in _MODELS:
        t0 = time.perf_counter()
        # The known-attack autoencoder can't stream from the day-split's train-only
        # Parquet subset (it would include real test rows for this split) -- forced
        # to the in-memory path by always passing calibrate_at_fpr, which already
        # does this (see array_benchmark.run_array_benchmark's own docstring).
        run = run_array_benchmark(
            ka_train, ka_test, model=model, seed=1337, train_parquet_paths=ka_train_full_parquet,
            calibrate_at_fpr=0.01,
        )
        _step(f"known_attack/{model}", t0)
        ka_runs[model] = run.model_dump(mode="json")
        _log(
            f"  {model}: roc_auc={run.metrics.get('roc_auc')} "
            f"recall@cal={run.metrics.get('recall_at_calibrated_threshold')}"
        )
    del ka_train, ka_test
    gc.collect()
    _step("after known_attack (freed)", time.perf_counter())

    partial = {
        "memory_steps": _STEPS,
        "day_split_benign_sampling_info": day_info,
        "known_attack_split_info": ka_info,
        "day_split_runs": day_runs,
        "known_attack_split_runs": ka_runs,
    }
    out_path = out_dir / "partial_cicids2017_v2.json"
    out_path.write_text(json.dumps(partial, indent=2), encoding="utf-8")
    _log(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
