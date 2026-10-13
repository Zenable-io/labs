# Copyright (c) 2026 Zenable, Inc.

"""The same program on Jev, a model that answers in probabilities.

Nothing in `program.py` changes. DSPy sees a TypeSafe client, sends the
signature to System One as a Choice over the `Literal`'s eight types, and reads
the probability Jev gives each one back as the answer.

Every answer lands in DSPy's cache, so running a program again over lines it
has already seen sends nothing. That is what makes calibrating free: a label
weight changes how DSPy reads the probabilities it already has, not what it
asks.

Two code paths, on purpose. `--fixtures` replays answers recorded from a real
run, loaded into that same cache, so every exercise here works without a key.
A request is looked up by everything DSPy would send, so edit the signature or
ask about a new line and the replay stops instead of answering a question you
used to be asking.
"""

import json
import os
from pathlib import Path
from typing import Any

import dspy
from dspy.experimental import TypeSafe
from pydantic import BaseModel, ConfigDict

from dspylab import program as lab
from dspylab.commits import TYPES

FIXTURE_FILE = Path(__file__).resolve().parent / "fixtures" / "recorded.json"


class Recording(BaseModel):
    """One request DSPy sent and the answers Jev gave it."""

    model_config = ConfigDict(frozen=True)

    request: dict[str, Any]
    answers: dict[str, Any]


class Recordings(BaseModel):
    """A real run's answers, and the model and host they came from."""

    model_config = ConfigDict(frozen=True)

    model: str
    base_url: str
    recordings: list[Recording]


class FixtureMiss(RuntimeError):
    """No recording matches this request."""


class _Replay(TypeSafe):
    """TypeSafe that answers only from the recording, and says so when it can't."""

    def _require_recorded(
        self, state: dict[str, Any], questions: dict[str, Any]
    ) -> None:
        if dspy.cache.get(self._request(state, questions)) is None:
            subject = state.get("inputs", {}).get("subject", "")
            raise FixtureMiss(
                f"no recording for {subject!r} as this program asks it. "
                "Put a key in ~/.env and drop --fixtures to ask Jev."
            )

    def __call__(
        self, state: dict[str, Any], questions: dict[str, Any]
    ) -> dict[str, Any]:
        self._require_recorded(state, questions)
        return super().__call__(state, questions)

    async def acall(
        self, state: dict[str, Any], questions: dict[str, Any]
    ) -> dict[str, Any]:
        self._require_recorded(state, questions)
        return await super().acall(state, questions)


def configure(fixtures: bool = False) -> TypeSafe:
    """Point DSPy at Jev, or at the answers a real run recorded."""
    if fixtures:
        saved = Recordings.model_validate_json(FIXTURE_FILE.read_text())
        # Memory only, so a replay never mixes recorded answers into the disk
        # cache a live run reads.
        dspy.configure_cache(enable_disk_cache=False)
        for item in saved.recordings:
            dspy.cache.put(
                item.request,
                {"model": saved.model, "usage": {}, "answers": item.answers},
            )
        # The cache key includes the host, so a replay has to ask the host the
        # answers were recorded from.
        lm: TypeSafe = _Replay(model=saved.model, base_url=saved.base_url)
    else:
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise SystemExit(
                "TYPESAFE_API_KEY is not set. Put it in ~/.env, "
                "or add --fixtures to replay a real run's answers."
            )
        lm = TypeSafe()
    dspy.configure(lm=lm)
    return lm


def build(weights: dict[str, float] | None = None) -> dspy.Predict:
    """`program.py`'s module; `weights` scale each type's probability before the pick."""
    module = lab.build()
    if weights:
        module.fields = {"commit_type": {"weights": dict(weights)}}
    return module


def weights_of(module: dspy.Predict) -> dict[str, float]:
    """The label weights a program carries, 1.0 for every type it leaves alone."""
    configured = module.fields.get("commit_type", {}).get("weights", {})
    return {
        commit_type: float(configured.get(commit_type, 1.0)) for commit_type in TYPES
    }


def probabilities(lm: TypeSafe) -> dict[str, float]:
    """What Jev gave each type in the last answer, whether live or cached."""
    return dict(lm.history[-1]["response"]["answers"]["commit_type"]["probabilities"])


def sent(lm: TypeSafe) -> int:
    """How many answers came from Jev rather than the cache, this process."""
    return sum(1 for entry in lm.history if not entry["cache_hit"])


def recordings(lm: TypeSafe) -> Recordings:
    """Every distinct request this process sent or read, with its answers.

    Usage is left out: the recording mirrors publicly, and what an answer cost
    is the vendor's number to publish, not ours.
    """
    seen: dict[str, Recording] = {}
    for entry in lm.history:
        key = json.dumps(entry["request"], sort_keys=True)
        seen.setdefault(
            key,
            Recording(request=entry["request"], answers=entry["response"]["answers"]),
        )
    return Recordings(
        model=lm.model, base_url=lm.base_url, recordings=list(seen.values())
    )
