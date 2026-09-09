"""`sm-ml-train` — run one reproducible training pipeline.

    python -m sm_ml_training --fixture --model-name graph_anomaly
    python -m sm_ml_training --config run.json

`run.json` is a `TrainingConfig`. `--fixture` is shorthand for the synthetic
fixture dataset (a plumbing check — no benchmark metric is claimed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .artifacts import write_artifact
from .config import ModelKind, TrainingConfig
from .pipeline import PipelineSkipped, TrainingPipeline

__all__ = ["main"]


def _build_config(args: argparse.Namespace) -> TrainingConfig:
    if args.config:
        return TrainingConfig.model_validate_json(Path(args.config).read_text(encoding="utf-8"))
    return TrainingConfig(
        model_name=args.model_name,
        model_kind=ModelKind(args.model_kind),
        seed=args.seed,
        output_dir=args.output_dir,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sm-ml-train", description="SentinelMesh graph-model training")
    parser.add_argument("--config", type=Path, help="path to a TrainingConfig JSON file")
    parser.add_argument("--fixture", action="store_true", help="use the synthetic fixture dataset")
    parser.add_argument("--model-name", default="graph_anomaly")
    parser.add_argument("--model-kind", default="structural", choices=[k.value for k in ModelKind])
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--output-dir", default="ml/artifacts/graph")
    parser.add_argument("--dry-run", action="store_true", help="run the pipeline but write no artifact")
    args = parser.parse_args(argv)

    config = _build_config(args)
    try:
        result = TrainingPipeline(config).run()
    except PipelineSkipped as exc:
        print(f"pipeline skipped: {exc}", file=sys.stderr)  # noqa: T201
        return 3

    for line in result.stage_log:
        print(line)  # noqa: T201
    print(json.dumps(result.metadata.model_dump(mode="json")["evaluation"], indent=2))  # noqa: T201

    if args.dry_run:
        return 0
    dest = write_artifact(result, config.output_dir)
    print(f"artifact written: {dest}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
