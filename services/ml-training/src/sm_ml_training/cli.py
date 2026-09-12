"""`sm-ml-train` — run one reproducible training pipeline, or a real tabular
IDS benchmark.

    python -m sm_ml_training --fixture --model-name graph_anomaly
    python -m sm_ml_training --config run.json
    python -m sm_ml_training benchmark --dataset nsl-kdd \
        --train ml/data/nsl-kdd/KDDTrain+.txt --test ml/data/nsl-kdd/KDDTest+.txt

`run.json` is a `TrainingConfig`. `--fixture` is shorthand for the synthetic
fixture dataset (a plumbing check — no benchmark metric is claimed). The
`benchmark` subcommand runs `sm_ml_training.benchmark` (R24) against a real,
locally-staged dataset file — see `ml/datasets/<name>/MANIFEST.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .artifacts import write_artifact
from .benchmark.harness import run_benchmark
from .benchmark.nsl_kdd import load_nsl_kdd
from .config import ModelKind, TrainingConfig
from .pipeline import PipelineSkipped, TrainingPipeline

__all__ = ["main"]

_BENCHMARK_LOADERS = {"nsl-kdd": load_nsl_kdd}


def _build_config(args: argparse.Namespace) -> TrainingConfig:
    if args.config:
        return TrainingConfig.model_validate_json(Path(args.config).read_text(encoding="utf-8"))
    return TrainingConfig(
        model_name=args.model_name,
        model_kind=ModelKind(args.model_kind),
        seed=args.seed,
        output_dir=args.output_dir,
    )


def _run_benchmark_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sm-ml-train benchmark", description="Real tabular IDS benchmark run"
    )
    parser.add_argument("--dataset", required=True, choices=sorted(_BENCHMARK_LOADERS))
    parser.add_argument("--train", required=True, type=Path, help="path to the train split file")
    parser.add_argument("--test", required=True, type=Path, help="path to the test split file")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--out", type=Path, help="write the BenchmarkRun as JSON to this path")
    args = parser.parse_args(argv)

    loader = _BENCHMARK_LOADERS[args.dataset]
    try:
        train, test = loader(args.train, args.test)
    except FileNotFoundError as exc:
        print(f"benchmark not run: {exc}", file=sys.stderr)  # noqa: T201
        return 3

    run = run_benchmark(train, test, seed=args.seed)
    print(run.model_dump_json(indent=2))  # noqa: T201
    if args.out:
        args.out.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"benchmark result written: {args.out}")  # noqa: T201
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "benchmark":
        return _run_benchmark_cli(argv[1:])

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
