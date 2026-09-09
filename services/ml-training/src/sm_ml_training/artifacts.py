"""Artifact handling — write a run's model + metadata to the registry layout.

    <output_dir>/<model_name>/<model_version>/
        model.json      # the trained parameters (structural) — a torch checkpoint for a GNN
        metadata.json   # ModelMetadata (seed, versions, dataset id + sha, git commit, evaluation)

`GraphModelRegistry` reads exactly this layout. Two runs with the same config and
dataset write byte-identical `model.json` and an identical `metadata.json` apart
from `created_at` and `git_commit`.
"""

from __future__ import annotations

import json
from pathlib import Path

from .pipeline import PipelineResult

__all__ = ["write_artifact"]


def write_artifact(result: PipelineResult, output_dir: str | Path) -> Path:
    meta = result.metadata
    dest = Path(output_dir) / meta.model_name / meta.model_version
    dest.mkdir(parents=True, exist_ok=True)

    (dest / "model.json").write_text(
        json.dumps(result.trained.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (dest / "metadata.json").write_text(
        meta.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (dest / "stage_log.txt").write_text("\n".join(result.stage_log) + "\n", encoding="utf-8")
    return dest
