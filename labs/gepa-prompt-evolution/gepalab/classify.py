"""Copyright (c) 2026 Zenable, Inc. Label a log line for on-call triage with one short prompt.

The artifact GEPA evolves here is the prompt itself. Scoring sends the prompt
and one line to the hosted model and reads one word back, so every score is a
paid call. The data is small and the search is capped for that reason, and the
same model does the reflecting.

Every answer goes through one `Scorer`. A live scorer memoises by prompt and
line, so re-scoring a parent on a minibatch it has already seen sends nothing,
and it keeps what it sent so a run can be written down. A replay scorer answers
only from that recording and stops on the first question it was never asked,
rather than inventing a label.
"""

import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

import litellm
from pydantic import BaseModel, ConfigDict

from gepalab.triage import HELD_OUT, LABELS, LINES, TRAIN, VALIDATION, LogLine

SEED_PROMPT = "Classify this log line as page, ticket, or ignore."
"""What a person writes first. Right about the obvious lines and guessing on the rest."""

OBJECTIVE = (
    "Write the instructions a model follows to label one log line for on-call "
    "triage as page, ticket, or ignore. The model answers with exactly one of "
    "those three words."
)

BACKGROUND = """\
The lines come from one company's systems. Each has exactly one right label:
`page` means wake someone now, `ticket` means a person deals with it on the
next working day, `ignore` means nobody needs to do anything. The log level
alone is a poor guide to the label.

The instructions are sent as the system prompt, the log line as the user
message, and the first of the three words in the reply is taken as the answer.
A reply with none of them scores zero. Scoring is exact match against the
human label, and the feedback for each line carries the reason behind it.
"""

CONCURRENCY = 4
"""Calls in flight at once. Enough to keep a forty-line split under a minute,
few enough that a provider rate limit never turns a lab step into a retry storm."""

_LABEL_RE = re.compile(r"\b(" + "|".join(LABELS) + r")\b", re.IGNORECASE)


class FixtureMiss(RuntimeError):
    """The recording holds no answer for this prompt and line."""


class Recording(BaseModel):
    """One question the model was asked, and what it answered."""

    model_config = ConfigDict(frozen=True, strict=True)

    prompt: str
    line: str
    answer: str


class Recordings(BaseModel):
    """A real run's answers, the model that gave them, and its reflections in order.

    Usage and cost are left out: the recording mirrors publicly, and what an
    answer cost is the vendor's number to publish.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    model: str
    classifications: tuple[Recording, ...]
    reflections: tuple[str, ...]


class Outcome(BaseModel):
    """What one prompt made the model answer for one line."""

    model_config = ConfigDict(frozen=True, strict=True)

    line: str
    expected: str
    answered: str
    reason: str
    correct: bool


def parse_label(reply: str) -> str:
    """The first label named in a reply, lower-cased, or the empty string."""
    found = _LABEL_RE.search(reply)
    return found.group(1).lower() if found else ""


def no_thinking(model: str) -> dict[str, Any]:
    """Request options that switch thinking off for `model`, where the provider allows it.

    Thinking models spend the output cap on reasoning first, so a 16-token label
    call comes back empty unless thinking is off.
    """
    if model.startswith("openrouter/"):
        return {"extra_body": {"reasoning": {"enabled": False}}}
    if model.startswith("openai/"):
        return {"reasoning_effort": "none"}
    return {}


def ask(model: str, prompt: str, line: str) -> str:
    """One classification call: the prompt as system message, the line as the user message."""
    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": line},
        ],
        temperature=0,
        max_tokens=16,
        timeout=60,
        num_retries=1,
        **no_thinking(model),
    )
    return response.choices[0].message.content or ""


class Scorer:
    """Answers for (prompt, line), memoised, from a model or from a recording."""

    def __init__(self, answer: Callable[[str, str], str], *, model: str) -> None:
        self._answer = answer
        self.model = model
        self.answers: dict[tuple[str, str], str] = {}
        self.calls = 0
        self._lock = Lock()

    @classmethod
    def live(cls, model: str) -> "Scorer":
        return cls(lambda prompt, line: ask(model, prompt, line), model=model)

    @classmethod
    def replay(cls, path: Path) -> "Scorer":
        if not path.exists():
            raise SystemExit(
                f"{path} does not exist. Put a key in ~/.env and run "
                "`python -m gepalab record` to write it, or drop --fixtures."
            )
        saved = Recordings.model_validate_json(path.read_text())

        def miss(prompt: str, line: str) -> str:
            raise FixtureMiss(
                f"no recorded answer for {line!r} under this prompt. "
                "Put a key in ~/.env and drop --fixtures to ask the model."
            )

        scorer = cls(miss, model=saved.model)
        scorer.answers = {
            (item.prompt, item.line): item.answer for item in saved.classifications
        }
        return scorer

    def classify(self, prompt: str, line: str) -> str:
        key = (prompt.strip(), line)
        with self._lock:
            answer = self.answers.get(key)
        if answer is not None:
            return answer
        answer = self._answer(key[0], line)
        with self._lock:
            self.answers[key] = answer
            self.calls += 1
        return answer

    def recordings(self, reflections: tuple[str, ...] = ()) -> Recordings:
        return Recordings(
            model=self.model,
            classifications=tuple(
                Recording(prompt=prompt, line=line, answer=answer)
                for (prompt, line), answer in self.answers.items()
            ),
            reflections=reflections,
        )


_SCORER: Scorer | None = None


def configure(scorer: Scorer) -> Scorer:
    """Make `scorer` the one every evaluation in this process goes through."""
    global _SCORER
    _SCORER = scorer
    return scorer


def scorer() -> Scorer:
    if _SCORER is None:
        raise RuntimeError("configure() a Scorer before scoring anything")
    return _SCORER


def judge(prompt: str, example: LogLine) -> Outcome:
    answered = parse_label(scorer().classify(prompt, example.line))
    return Outcome(
        line=example.line,
        expected=example.label,
        answered=answered,
        reason=example.reason,
        correct=answered == example.label,
    )


def evaluate(candidate: str, example: LogLine) -> tuple[float, dict[str, Any]]:
    """Score one prompt on one line, with the feedback reflection reads.

    The reason behind the label goes back on every line, right or wrong. A
    correct answer for the wrong reason is the next proposal's problem, and the
    reason is the only thing in the feedback a prompt can learn a rule from.
    """
    outcome = judge(candidate, example)
    if outcome.correct:
        return 1.0, {
            "line": example.line,
            "feedback": f"Correct, {example.label}: {example.reason}",
        }
    answered = outcome.answered or "(no label)"
    return 0.0, {
        "line": example.line,
        "expected": example.label,
        "answered": answered,
        "feedback": f"Expected {example.label}, answered {answered}. {example.reason}",
    }


def report(prompt: str, examples: tuple[LogLine, ...] = LINES) -> list[Outcome]:
    """Every line and what the prompt made the model answer, wrong ones first."""
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        outcomes = list(pool.map(lambda example: judge(prompt, example), examples))
    return sorted(outcomes, key=lambda outcome: outcome.correct)


def score(prompt: str, examples: tuple[LogLine, ...]) -> float:
    """Share of `examples` the prompt labels exactly right, 0.0 to 1.0."""
    if not examples:
        return 0.0
    return sum(outcome.correct for outcome in report(prompt, examples)) / len(examples)


def license_sidecar(path: Path) -> None:
    """The copyright notice the published rig needs beside a data file it ships."""
    path.with_name(path.name + ".license").write_text(
        "Copyright (c) 2026 Zenable, Inc.\n"
    )


def write_recordings(saved: Recordings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved.model_dump(), indent=2, sort_keys=True) + "\n")
    license_sidecar(path)


SPLITS: dict[str, tuple[LogLine, ...]] = {
    "train": TRAIN,
    "validation": VALIDATION,
    "held-out": HELD_OUT,
}
