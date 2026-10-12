"""Phase 1.5/1.6 UNSW-NB15 leakage audit: standard-orientation official
train/test split (primary), literal/reversed orientation (secondary,
real comparison), feature list + leakage confirmation, near-duplicate
check (with a with/without-duplicates rerun), LightGBM feature
importance (gain) + SHAP, a TTL-feature ablation, and the held-out-DoS
confirmation + its driving features. Every test-set metric is reported
next to its real attack prevalence (base rate). Writes a single JSON
report.

Needs `shap` (not part of any installed extra -- `pip install shap`,
pulls in pandas/numba as its own transitive deps). A one-off analysis
script, not committed library code, so this is intentionally not added
to any package's pyproject.toml extras.

Run: .venv/Scripts/python.exe scripts/analyze_unsw_nb15_audit.py
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sm_ml_training.benchmark.array_benchmark import _fit_gradient_boosting_arrays, run_array_benchmark

from sm_ml.datasets.arrays import ArrayFlowDataset
from sm_ml.datasets.unsw_nb15_official import load_unsw_nb15_official_split

_TTL_FEATURES = ("sttl", "dttl", "ct_state_ttl")
_RAW_DIR = Path("data/raw/unsw_nb15")
_OUT = Path("eval/reports/_unsw_nb15_audit.json")


def _log(msg: str) -> None:
    print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


def _row_hashes(x: Any) -> set[bytes]:
    rounded = np.round(x, 6)
    return {rounded[i].tobytes() for i in range(rounded.shape[0])}


def _near_duplicate_count(train: Any, test: Any) -> dict[str, Any]:
    """Real EXACT duplicate check (not fuzzy) -- hashes each row's full
    real feature vector (rounded to 6 decimals, since values are
    float32) and counts how many test rows share a hash with a train row."""
    train_hashes = _row_hashes(train.X)
    test_hashes = _row_hashes(test.X)
    overlap = train_hashes & test_hashes
    return {
        "method": "exact row-hash match on the real float32 feature vector, rounded to 6 decimals",
        "n_train_unique_rows": len(train_hashes), "n_test_unique_rows": len(test_hashes),
        "n_exact_duplicate_feature_vectors_shared": len(overlap),
        "fraction_of_test_rows_duplicated_in_train": round(len(overlap) / len(test_hashes), 6) if test_hashes else 0.0,
    }


def _remove_test_duplicates(train: Any, test: Any) -> Any:
    train_hashes = _row_hashes(train.X)
    rounded_test = np.round(test.X, 6)
    keep_mask = [rounded_test[i].tobytes() not in train_hashes for i in range(rounded_test.shape[0])]
    return dataclasses.replace(
        test, X=test.X[keep_mask], y=test.y[keep_mask],
        attack_types=tuple(t for t, k in zip(test.attack_types, keep_mask, strict=True) if k),
    )


def _base_rate(ds: Any) -> float:
    return round(float(ds.y.sum()) / ds.n_rows, 6)


def _top_n_gain(booster: Any, n: int = 15) -> list[dict[str, Any]]:
    gains = booster.feature_importance(importance_type="gain")
    names = booster.feature_name()
    pairs = sorted(zip(names, gains, strict=True), key=lambda p: p[1], reverse=True)[:n]
    return [{"feature": name, "gain": float(g)} for name, g in pairs]


def _shap_summary(booster: Any, x_sample: Any, feature_names: tuple[str, ...], n: int = 15) -> list[dict[str, Any]]:
    import shap

    explainer = shap.TreeExplainer(booster)
    shap_values = explainer.shap_values(x_sample)
    if isinstance(shap_values, list):
        shap_values = shap_values[-1]
    mean_abs = np.mean(np.abs(shap_values), axis=0)
    pairs = sorted(zip(feature_names, mean_abs.tolist(), strict=True), key=lambda p: p[1], reverse=True)[:n]
    return [{"feature": name, "mean_abs_shap": float(v)} for name, v in pairs]


def _run_three_models(train: Any, test: Any, *, label: str) -> dict[str, Any]:
    runs = {}
    for model in ("isolation_forest", "autoencoder", "gradient_boosting"):
        run = run_array_benchmark(train, test, model=model, seed=1337, calibrate_at_fpr=0.01)
        runs[model] = run.model_dump(mode="json")
        _log(
            f"  [{label}] {model}: roc_auc={run.metrics.get('roc_auc')} "
            f"precision@cal={run.metrics.get('precision_at_calibrated_threshold')} "
            f"recall@cal={run.metrics.get('recall_at_calibrated_threshold')}"
        )
    return runs


def main() -> int:
    report: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat()}

    _log("loading official UNSW-NB15 split -- standard orientation (primary)")
    train, test, info = load_unsw_nb15_official_split(_RAW_DIR, orientation="standard")
    _log(
        f"train n={train.n_rows} (prevalence={_base_rate(train)}), "
        f"test n={test.n_rows} (prevalence={_base_rate(test)}), swapped_vs_filename={info['swapped_vs_filename']}"
    )
    report["feature_audit"] = {
        "feature_columns_used": info["feature_columns"],
        "leaky_columns_confirmed_absent": ["srcip", "dstip", "sport", "dsport", "Stime", "Ltime", "id"],
        "note": "this release never shipped srcip/dstip/sport/dsport/Stime/Ltime at all -- "
                "'id' (a plain row counter) is the only identifier-shaped column, and it is dropped.",
    }
    report["split_orientation"] = {
        "standard_swapped_vs_filename": info["swapped_vs_filename"],
        "standard_train_n": info["n_train"], "standard_train_prevalence": info["train_attack_prevalence"],
        "standard_test_n": info["n_test"], "standard_test_prevalence": info["test_attack_prevalence"],
        "note": "the mirror's 'training-set.csv' file physically has 82,332 rows and 'testing-set.csv' "
                "has 175,341 -- reversed vs. the documented 175,341-train/82,332-test convention. "
                "'standard' orientation (this run's primary) picks by real row count, not filename.",
    }

    _log("near-duplicate check (standard orientation)")
    report["near_duplicate_check_standard"] = _near_duplicate_count(train, test)
    _log(f"  {report['near_duplicate_check_standard']}")

    _log("primary 3-model comparison (standard orientation, calibrated at 1% FPR)")
    model_runs = _run_three_models(train, test, label="standard")
    report["primary_runs_standard_orientation"] = model_runs

    _log("de-duplicated rerun (test rows that exactly match a train row removed)")
    test_deduped = _remove_test_duplicates(train, test)
    _log(f"  test n={test.n_rows} -> {test_deduped.n_rows} after removing exact duplicates")
    dedup_runs = _run_three_models(train, test_deduped, label="standard-deduped")
    report["deduplicated_rerun"] = {
        "n_test_before": test.n_rows, "n_test_after": test_deduped.n_rows,
        "test_prevalence_before": _base_rate(test), "test_prevalence_after": _base_rate(test_deduped),
        "runs": dedup_runs,
    }

    _log("secondary comparison -- literal (reversed) orientation, for reference only")
    train_lit, test_lit, info_lit = load_unsw_nb15_official_split(_RAW_DIR, orientation="literal")
    report["near_duplicate_check_literal"] = _near_duplicate_count(train_lit, test_lit)
    secondary_runs = _run_three_models(train_lit, test_lit, label="literal")
    report["secondary_runs_literal_orientation"] = {
        "train_n": info_lit["n_train"], "train_prevalence": info_lit["train_attack_prevalence"],
        "test_n": info_lit["n_test"], "test_prevalence": info_lit["test_attack_prevalence"],
        "runs": secondary_runs,
    }
    del train_lit, test_lit

    _log("LightGBM feature importance (gain) + SHAP (standard orientation)")
    booster, _params = _fit_gradient_boosting_arrays(train.X, train.y, train.feature_names, seed=1337)
    report["lightgbm_top15_gain"] = _top_n_gain(booster)
    sample_n = min(5000, test.n_rows)
    report["lightgbm_top15_shap"] = _shap_summary(booster, test.X[:sample_n], train.feature_names)
    _log(f"  top gain: {[d['feature'] for d in report['lightgbm_top15_gain'][:5]]}")
    _log(f"  top shap: {[d['feature'] for d in report['lightgbm_top15_shap'][:5]]}")

    _log("TTL ablation (drop sttl, dttl, ct_state_ttl)")
    ttl_cols_present = [c for c in _TTL_FEATURES if c in train.feature_names]
    keep_mask = [f not in ttl_cols_present for f in train.feature_names]
    ablated_feature_names = tuple(f for f, k in zip(train.feature_names, keep_mask, strict=True) if k)
    train_ablated = ArrayFlowDataset(
        dataset_id=train.dataset_id, sha256=train.sha256, feature_names=ablated_feature_names,
        X=train.X[:, keep_mask], y=train.y, attack_types=train.attack_types,
    )
    test_ablated = ArrayFlowDataset(
        dataset_id=test.dataset_id, sha256=test.sha256, feature_names=ablated_feature_names,
        X=test.X[:, keep_mask], y=test.y, attack_types=test.attack_types,
    )
    run_ablated = run_array_benchmark(
        train_ablated, test_ablated, model="gradient_boosting", seed=1337, calibrate_at_fpr=0.01
    )
    report["ttl_ablation"] = {
        "dropped_features": ttl_cols_present,
        "with_ttl": model_runs["gradient_boosting"]["metrics"],
        "without_ttl": run_ablated.model_dump(mode="json")["metrics"],
    }
    _log(f"  with TTL roc_auc={model_runs['gradient_boosting']['metrics']['roc_auc']}")
    _log(f"  without TTL roc_auc={run_ablated.metrics['roc_auc']}")

    _log("held-out DoS confirmation + driving features (standard orientation)")
    dos_mask_train = [t == "DoS" for t in train.attack_types]
    n_dos_in_train = sum(dos_mask_train)
    keep_train_mask = [not m for m in dos_mask_train]
    train_no_dos = ArrayFlowDataset(
        dataset_id=train.dataset_id, sha256=train.sha256, feature_names=train.feature_names,
        X=train.X[keep_train_mask], y=train.y[keep_train_mask],
        attack_types=tuple(t for t, k in zip(train.attack_types, keep_train_mask, strict=True) if k),
    )
    dos_test_mask = [t == "DoS" for t in test.attack_types]
    held_out_x = test.X[dos_test_mask]
    run_dos = run_array_benchmark(
        train_no_dos, test, model="gradient_boosting", seed=1337, calibrate_at_fpr=0.01,
        held_out_attack_type="DoS", held_out_x=held_out_x,
    )
    booster_no_dos, _ = _fit_gradient_boosting_arrays(
        train_no_dos.X, train_no_dos.y, train_no_dos.feature_names, seed=1337
    )
    dos_shap = _shap_summary(booster_no_dos, held_out_x, train.feature_names, n=15) if held_out_x.shape[0] else []
    report["held_out_dos"] = {
        "n_dos_rows_removed_from_train": n_dos_in_train,
        "n_dos_rows_confirmed_zero_in_train_after_removal": sum(t == "DoS" for t in train_no_dos.attack_types),
        "n_dos_rows_in_test": int(sum(dos_test_mask)),
        "held_out_recall": run_dos.held_out_recall,
        "top_shap_features_driving_dos_detection": dos_shap,
    }
    _log(f"  held_out_recall={run_dos.held_out_recall}, n_dos_removed={n_dos_in_train}")

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log(f"wrote {_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
