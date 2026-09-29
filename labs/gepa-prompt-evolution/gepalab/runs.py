"""Copyright (c) 2026 Zenable, Inc. One small record of a run, written the same way whoever produced it.

A learner with a reflection key writes this file from their own search; a
learner without one reads the copy this rig ships. Both go through `SavedRun`,
so the commands that read a run never have to ask which kind they were handed.

GEPA's own result object carries far more than this — every candidate, every
per-example subscore, the whole Pareto structure. What survives here is what
the lab reads out loud: the seed, the winner, the candidates that were kept,
and how much of the budget it took to find them.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from gepalab.regex_task import SPLITS, score


class KeptCandidate(BaseModel):
    """One candidate GEPA kept, and how it did on the validation split."""

    model_config = ConfigDict(frozen=True, strict=True)

    text: str
    validation: float


class SavedRun(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    name: str
    model: str
    """The reflection model. The thing being scored never was a model."""

    seed: str
    best_candidate: str
    evaluations: int
    frontier_size: int
    lineage: tuple[KeptCandidate, ...]
    scores: dict[str, float]
    """Best candidate by split name, as measured when the run was saved."""

    seed_scores: dict[str, float]


def _candidate_text(candidate: Any) -> str:
    if isinstance(candidate, dict):
        return "\n".join(str(value) for value in candidate.values())
    return str(candidate)


def save(result: Any, path: Path, *, seed: str, model: str) -> SavedRun:
    best = _candidate_text(result.best_candidate)
    lineage = tuple(
        KeptCandidate(text=_candidate_text(candidate), validation=float(aggregate))
        for candidate, aggregate in zip(
            result.candidates, result.val_aggregate_scores, strict=False
        )
    )
    saved = SavedRun(
        name=path.parent.name,
        model=model,
        seed=seed,
        best_candidate=best,
        evaluations=int(getattr(result, "total_metric_calls", 0) or 0),
        frontier_size=len(result.candidates),
        lineage=lineage,
        scores={name: score(best, examples) for name, examples in SPLITS.items()},
        seed_scores={name: score(seed, examples) for name, examples in SPLITS.items()},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved.model_dump(), indent=2, sort_keys=True) + "\n")
    return saved


def load(path: Path) -> SavedRun:
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Run `python -m gepalab evolve` to make one, "
            "or pass the path of a run you already have."
        )
    # From JSON rather than from a parsed dict: `lineage` is a tuple, and a
    # strict model reads a JSON array as one while it refuses a Python list.
    return SavedRun.model_validate_json(path.read_text())
