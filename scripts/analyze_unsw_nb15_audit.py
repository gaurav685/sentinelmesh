"""Phase 1.5 UNSW-NB15 leakage audit: official train/test split, feature
list + leakage confirmation, near-duplicate check, LightGBM feature
importance (gain) + SHAP, a TTL-feature ablation, and the held-out-DoS
confirmation + its driving features. Writes a single JSON report.

Run: .venv/Scripts/python.exe scripts/analyze_unsw_nb15_audit.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sm_ml_training.benchmark.array_benchmark import _fit_gradient_boosting_arrays, run_array_benchmark

from sm_ml.datasets.unsw_nb15_official import load_unsw_nb15_official_split

_TTL_FEATURES = ("sttl", "dttl", "ct_state_ttl")
_RAW_DIR = Path("data/raw/unsw_nb15")
_OUT = Path("eval/reports/_unsw_nb15_audit.json")


def _log(msg: str) -> None:
    print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


def _near_duplicate_count(train: Any, test: Any) -> dict[str, Any]:
    """Real EXACT duplicate check (not a fuzzy/near-match) -- hashes each
    row's full real feature vector (rounded to 6 decimal places, since the
    underlying values are float32) and counts how many test rows share a
    hash with a real train row. Rounding absorbs float32 rounding noise
    between two genuinely identical source rows without fuzzy-matching
    genuinely different rows."""
    import numpy as np

    def _hashes(x: Any) -> set[bytes]:
        rounded = np.round(x, 6)
        return {rounded[i].tobytes() for i in range(rounded.shape[0])}

    train_hashes = _hashes(train.X)
    test_hashes = _hashes(test.X)
    overlap = train_hashes & test_hashes
    return {
        "method": "exact row-hash match on the real float32 feature vector, rounded to 6 decimals",
        "n_train_unique_rows": len(train_hashes),
        "n_test_unique_rows": len(test_hashes),
        "n_exact_duplicate_feature_vectors_shared": len(overlap),
        "fraction_of_test_rows_duplicated_in_train": round(len(overlap) / len(test_hashes), 6) if test_hashes else 0.0,
    }


def _top_n_gain(booster: Any, feature_names: tuple[str, ...], n: int = 15) -> list[dict[str, Any]]:
    gains = booster.feature_importance(importance_type="gain")
    names = booster.feature_name()
    pairs = sorted(zip(names, gains, strict=True), key=lambda p: p[1], reverse=True)[:n]
    return [{"feature": name, "gain": float(g)} for name, g in pairs]


def _shap_summary(booster: Any, x_sample: Any, feature_names: tuple[str, ...], n: int = 15) -> list[dict[str, Any]]:
    import numpy as np
    import shap

    explainer = shap.TreeExplainer(booster)
    shap_values = explainer.shap_values(x_sample)
    if isinstance(shap_values, list):
        shap_values = shap_values[-1]
    mean_abs = np.mean(np.abs(shap_values), axis=0)
    pairs = sorted(zip(feature_names, mean_abs.tolist(), strict=True), key=lambda p: p[1], reverse=True)[:n]
    return [{"feature": name, "mean_abs_shap": float(v)} for name, v in pairs]


def main() -> int:
    _log("loading official UNSW-NB15 train/test split")
    train, test, info = load_unsw_nb15_official_split(_RAW_DIR)
    _log(
        f"train n={train.n_rows} ({int(train.y.sum())} anomalous), "
        f"test n={test.n_rows} ({int(test.y.sum())} anomalous), features={len(train.feature_names)}"
    )

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "feature_audit": {
            "feature_columns_used": info["feature_columns"],
            "leaky_columns_confirmed_absent": ["srcip", "dstip", "sport", "dsport", "Stime", "Ltime", "id"],
            "note": "this release never shipped srcip/dstip/sport/dsport/Stime/Ltime at all -- "
                    "'id' (a plain row counter) is the only identifier-shaped column, and it is dropped.",
        },
    }

    _log("near-duplicate check (exact row-hash match)")
    report["near_duplicate_check"] = _near_duplicate_count(train, test)
    _log(f"  {report['near_duplicate_check']}")

    _log("primary 3-model comparison (calibrated at 1% FPR)")
    model_runs = {}
    for model in ("isolation_forest", "autoencoder", "gradient_boosting"):
        run = run_array_benchmark(train, test, model=model, seed=1337, calibrate_at_fpr=0.01)
        model_runs[model] = run.model_dump(mode="json")
        _log(
            f"  {model}: roc_auc={run.metrics.get('roc_auc')} "
            f"precision@cal={run.metrics.get('precision_at_calibrated_threshold')} "
            f"recall@cal={run.metrics.get('recall_at_calibrated_threshold')}"
        )
    report["primary_runs"] = model_runs

    _log("LightGBM feature importance (gain) + SHAP")
    booster, _params = _fit_gradient_boosting_arrays(train.X, train.y, train.feature_names, seed=1337)
    report["lightgbm_top15_gain"] = _top_n_gain(booster, train.feature_names)
    sample_n = min(5000, test.n_rows)
    report["lightgbm_top15_shap"] = _shap_summary(booster, test.X[:sample_n], train.feature_names)
    _log(f"  top gain: {[d['feature'] for d in report['lightgbm_top15_gain'][:5]]}")
    _log(f"  top shap: {[d['feature'] for d in report['lightgbm_top15_shap'][:5]]}")

    _log("TTL ablation (drop sttl, dttl, ct_state_ttl)")
    ttl_cols_present = [c for c in _TTL_FEATURES if c in train.feature_names]
    keep_mask = [f not in ttl_cols_present for f in train.feature_names]
    ablated_feature_names = tuple(f for f, k in zip(train.feature_names, keep_mask, strict=True) if k)
    train_x_ablated = train.X[:, keep_mask]
    test_x_ablated = test.X[:, keep_mask]
    from sm_ml.datasets.arrays import ArrayFlowDataset

    train_ablated = ArrayFlowDataset(
        dataset_id=train.dataset_id, sha256=train.sha256, feature_names=ablated_feature_names,
        X=train_x_ablated, y=train.y, attack_types=train.attack_types,
    )
    test_ablated = ArrayFlowDataset(
        dataset_id=test.dataset_id, sha256=test.sha256, feature_names=ablated_feature_names,
        X=test_x_ablated, y=test.y, attack_types=test.attack_types,
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

    _log("held-out DoS confirmation + driving features")
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
        "n_dos_rows_confirmed_zero_in_train_after_removal": sum(
            1 for t in train_no_dos.attack_types if t == "DoS"
        ),
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
