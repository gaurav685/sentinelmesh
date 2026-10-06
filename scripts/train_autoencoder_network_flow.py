#!/usr/bin/env python3
"""Train and export a real autoencoder artifact for `autoencoder_network_flow`
(remediation items 6/11/12/13 -- the autoencoder's serving code existed with
no training loop and no checkpoint until this script).

    python scripts/train_autoencoder_network_flow.py \
        --train-file C:\\Sentinel_Mesh\\archive\\KDDTrain+.txt \
        --eval-file  C:\\Sentinel_Mesh\\archive\\KDDTest+.txt \
        --out ml/artifacts/autoencoder_network_flow/v1

Dataset: NSL-KDD (public, locally staged). CICIDS2017 and UNSW-NB15 were
investigated for this and are BLOCKED -- both now require a manual
registration/access step at the source that cannot be scripted from this
environment (see `docs/PRIORITY_REMEDIATION_PLAN.md`); the repository owner
confirmed training on NSL-KDD now instead of blocking on that.

Feature extraction reuses this repo's own real, production
`sm_ml.features.extract_features` -- the exact function detection-engine
calls at inference time -- via the same NSL-KDD-row mapping
`scripts/train_isolation_forest_network_flow.py` already uses, for
structural train/serve parity between the two models. The same honest gap
applies here: NSL-KDD provides no dst_port/packet-count/direction, so those
dimensions are constant zero in both training and inference.

Trained on the **benign-only** subset of the train split (unlike the
Isolation Forest script, which fits on the whole split) -- an autoencoder's
anomaly signal is reconstruction error against a *learned model of normal
traffic*; fitting it on ~48% attack rows (NSL-KDD's train split is
deliberately near-balanced) would teach it to reconstruct attacks well too,
destroying the signal. This matches how `sm_ml_training.benchmark.harness`
already fits both of its models and how `detection-engine` fits the
statistical detector in production (ADR-013) -- the same convention, not a
new one invented for this script.

`--error-percentile` (default 99, matching `AutoencoderSpec.error_quantile`'s
default) sets the anomaly threshold at that percentile of the TRAINING set's
own reconstruction error -- a real, principled choice, not a fabricated
number. NSL-KDD's label is never used for training or thresholding, only
for the optional held-out `--eval-file` sanity check.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import torch
from torch import nn

from sm_contracts import CanonicalEventPayload, CanonicalKind, EntityKind, EntityRef, EventType
from sm_ml.features import extract_features
from sm_ml.models.autoencoder import AutoencoderSpec, build_module

_LABEL_COL = 41
_N_COLS = 43
_PROTOCOL_TYPE = 1
_SRC_BYTES = 4
_DST_BYTES = 5

MODEL_NAME = "autoencoder_network_flow"
MODEL_VERSION = "nsl-kdd-v1"


def _read_rows(path: Path, limit: int | None) -> list[list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"NSL-KDD file not found: {path}")
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != _N_COLS:
            raise ValueError(f"expected {_N_COLS} columns, got {len(parts)}: {line[:80]!r}")
        rows.append(parts)
        if limit is not None and len(rows) >= limit:
            break
    if not rows:
        raise ValueError(f"no rows read from {path}")
    return rows


def _row_to_vector(row: list[str], now: datetime) -> list[float]:
    actor = EntityRef(kind=EntityKind.ip, value="10.50.0.1")
    target = EntityRef(kind=EntityKind.ip, value="10.60.0.1")
    canonical = CanonicalEventPayload(
        kind=CanonicalKind.network_flow,
        occurred_at=now,
        action="connected_to",
        outcome=row[3],
        actor=actor,
        target=target,
        entities=[actor, target],
        raw_event_id=uuid4(),
        raw_event_type=EventType.telemetry_network_flow,
        attributes={
            "protocol": row[_PROTOCOL_TYPE],
            "bytes_sent": int(row[_SRC_BYTES]),
            "bytes_received": int(row[_DST_BYTES]),
        },
    )
    return extract_features(canonical).vector


def _feature_meta(now: datetime) -> tuple[tuple[str, ...], str]:
    result = extract_features(
        CanonicalEventPayload(
            kind=CanonicalKind.network_flow, occurred_at=now, action="connected_to",
            raw_event_id=uuid4(), raw_event_type=EventType.telemetry_network_flow, attributes={},
        )
    )
    return result.names, result.schema_version


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-file", required=True)
    ap.add_argument("--eval-file", default=None, help="Optional labelled file for a held-out sanity check")
    ap.add_argument("--out", required=True, help="Output dir, e.g. ml/artifacts/autoencoder_network_flow/v1")
    ap.add_argument("--limit", type=int, default=None, help="Cap training rows (default: use the whole file)")
    ap.add_argument("--hidden-dims", type=int, nargs="+", default=[16, 8])
    ap.add_argument("--error-percentile", type=float, default=99.0)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-fraction", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    now = datetime.now(UTC)
    all_rows = _read_rows(Path(args.train_file), args.limit)
    benign_rows = [r for r in all_rows if r[_LABEL_COL] == "normal"]
    print(f"read {len(all_rows)} real NSL-KDD rows, {len(benign_rows)} benign (fit set)")

    feature_names, schema_version = _feature_meta(now)
    x_all = torch.tensor([_row_to_vector(r, now) for r in benign_rows], dtype=torch.float32)

    idx = list(range(x_all.shape[0]))
    random.shuffle(idx)
    n_val = max(1, round(len(idx) * args.val_fraction))
    val_idx = torch.tensor(idx[:n_val], dtype=torch.long)
    train_idx = torch.tensor(idx[n_val:], dtype=torch.long)
    x_train, x_val = x_all[train_idx], x_all[val_idx]
    print(f"split: {x_train.shape[0]} train / {x_val.shape[0]} val benign rows, {x_all.shape[1]} features")

    spec = AutoencoderSpec(
        input_dim=x_all.shape[1], hidden_dims=tuple(args.hidden_dims),
        error_quantile=args.error_percentile / 100.0,
    )
    module = build_module(spec)
    optimizer = torch.optim.Adam(module.parameters(), lr=args.lr)
    loss_fn = nn.MSELoss()

    n_train = x_train.shape[0]
    best_val_loss = float("inf")
    best_state = None
    patience, bad_epochs = 8, 0
    for epoch in range(args.epochs):
        module.train()
        perm = torch.randperm(n_train)
        epoch_loss = 0.0
        for start in range(0, n_train, args.batch_size):
            batch_idx = perm[start : start + args.batch_size]
            batch = x_train[batch_idx]
            optimizer.zero_grad()
            recon = module(batch)
            loss = loss_fn(recon, batch)
            loss.backward()
            optimizer.step()
            epoch_loss += float(loss.item()) * batch.shape[0]
        epoch_loss /= n_train

        module.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(module(x_val), x_val).item())
        print(f"epoch {epoch + 1}/{args.epochs}  train_mse={epoch_loss:.6f}  val_mse={val_loss:.6f}")

        if val_loss < best_val_loss - 1e-6:
            best_val_loss, best_state, bad_epochs = val_loss, {k: v.clone() for k, v in module.state_dict().items()}, 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                print(f"early stopping at epoch {epoch + 1} (no val improvement for {patience} epochs)")
                break

    assert best_state is not None
    module.load_state_dict(best_state)
    module.eval()

    with torch.no_grad():
        train_errors = torch.mean((module(x_train) - x_train) ** 2, dim=1)
    threshold = float(torch.quantile(train_errors, args.error_percentile / 100.0).item())
    print(f"final best val_mse={best_val_loss:.6f}, error threshold (p{args.error_percentile:.0f})={threshold:.6f}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(module, out_dir / "model.pt")
    metadata = {
        "model_version": MODEL_VERSION,
        "method": "autoencoder",
        "input_dim": spec.input_dim,
        "hidden_dims": list(spec.hidden_dims),
        "error_quantile": spec.error_quantile,
        "normalisation_k": spec.normalisation_k,
        "feature_names": list(feature_names),
        "feature_schema_version": schema_version,
        "error_threshold": threshold,
        "task": "anomaly_score",
        "training": {
            "epochs_run": epoch + 1,
            "best_val_mse": best_val_loss,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "seed": args.seed,
            "optimizer": "Adam",
        },
        "trained_on": {
            "dataset": "NSL-KDD (public)",
            "file": str(args.train_file),
            "row_count_total": len(all_rows),
            "row_count_benign_fit": len(benign_rows),
            "trained_at": now.isoformat(),
        },
        "known_limitations": (
            "NSL-KDD provides no dst_port, packet counts, or direction -- those "
            "feature dimensions are constant zero in this training set and at "
            "inference time for data replayed from it."
        ),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'model.pt'} and {out_dir / 'metadata.json'}")

    if args.eval_file:
        eval_rows = _read_rows(Path(args.eval_file), args.limit)
        x_eval = torch.tensor([_row_to_vector(r, now) for r in eval_rows], dtype=torch.float32)
        with torch.no_grad():
            eval_errors = torch.mean((module(x_eval) - x_eval) ** 2, dim=1)
        predicted_anomaly = (eval_errors >= threshold).tolist()
        true_attack = [r[_LABEL_COL] != "normal" for r in eval_rows]
        tp = sum(1 for p, y in zip(predicted_anomaly, true_attack, strict=True) if p and y)
        fp = sum(1 for p, y in zip(predicted_anomaly, true_attack, strict=True) if p and not y)
        fn = sum(1 for p, y in zip(predicted_anomaly, true_attack, strict=True) if not p and y)
        tn = sum(1 for p, y in zip(predicted_anomaly, true_attack, strict=True) if not p and not y)
        print()
        print(f"held-out sanity check on {args.eval_file} ({len(eval_rows)} rows, label used ONLY for this printout):")
        print(f"  tp={tp} fp={fp} fn={fn} tn={tn}")
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        print(f"  precision={precision:.3f} recall={recall:.3f}")
        print(
            "  (threshold came only from the training set's own benign-only "
            "error distribution; labels were never used for fitting or thresholding.)"
        )


if __name__ == "__main__":
    main()
