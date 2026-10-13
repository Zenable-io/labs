"""Copyright (c) 2026 Zenable, Inc. Pull the request id out of a log line with one regular expression.

The artifact GEPA evolves here is the pattern itself, and nothing in the loop
is a language model: applying a pattern to forty short lines costs nothing and
takes microseconds, so the whole budget is spent on reflection rather than on
rollouts. That is the cheapest way to watch the search work.

A candidate reports the empty string when it matches nothing, which is the
right answer for the six lines that carry no request id. Scoring is exact
string equality, so a pattern that finds the id and drags a quote along with it
scores zero on that line, the same as one that found nothing.
"""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from gepalab.loglines import HELD_OUT, LINES, TRAIN, VALIDATION, LogLine

SEED_PATTERN = r"req_id=(\w+)"
"""What a person writes after reading the first few lines of the log.

It is right about the lines it was written from and silent everywhere else,
which is the honest starting point for a search that has to earn its score.
"""

OBJECTIVE = (
    "Write one Python regular expression that captures the request id from a log "
    "line, and captures nothing on a line that has no request id."
)

BACKGROUND = """\
The lines come from five services using five different logging libraries. The
request id appears as `req_id=`, `request-id:`, `rid=`, a JSON `request_id` or
`requestId` field, or in square brackets after the log level. Some lines quote
the value with single or double quotes; some put a comma straight after it. Ids
are not all the same shape: six hex characters, `r-0091`, a UUID, `RQ-2026-03-04-0817`
and `req_8f2270` all appear.

Several lines carry a field that looks like the answer and is not: `session_id`,
`parent_id`, `trace_id`, `correlation_id`, `trace=` and `span=`. Six lines carry
no request id at all and their expected answer is the empty string.

The pattern is used with `re.search`. The value captured is group `id` when the
pattern defines that named group, otherwise group 1, otherwise the whole match.
Scoring is exact string equality against the expected id, over the whole line.
"""

_MAX_LINE = 4000
"""Lines are far shorter than this. The cap is here because a proposed pattern
can backtrack badly, and a bounded input is the only thing that keeps a bad
candidate from stalling the run on `re`, which has no match timeout."""


class PatternError(ValueError):
    """The candidate is not a regular expression Python can compile."""


class Outcome(BaseModel):
    """What one candidate did to one line."""

    model_config = ConfigDict(frozen=True, strict=True)

    line: str
    expected: str
    captured: str
    correct: bool


def capture(pattern: str, line: str) -> str:
    """Apply `pattern` to `line` and return what it captured, or the empty string."""
    try:
        compiled = re.compile(pattern.strip())
    except re.error as error:
        raise PatternError(str(error)) from error

    found = compiled.search(line[:_MAX_LINE])
    if found is None:
        return ""
    if "id" in (compiled.groupindex or {}):
        return found.group("id") or ""
    if compiled.groups:
        return found.group(1) or ""
    return found.group(0)


def judge(pattern: str, example: LogLine) -> Outcome:
    captured = capture(pattern, example.line)
    return Outcome(
        line=example.line,
        expected=example.request_id,
        captured=captured,
        correct=captured == example.request_id,
    )


def evaluate(candidate: str, example: LogLine) -> tuple[float, dict[str, Any]]:
    """Score one candidate on one line, with the feedback reflection reads.

    A compile error scores zero and says so in the feedback rather than raising:
    a proposal that does not compile is a normal move in the search, and the
    error message is the most useful thing the next proposal can be told.
    """
    try:
        outcome = judge(candidate, example)
    except PatternError as error:
        return 0.0, {
            "line": example.line,
            "expected": example.request_id,
            "feedback": f"The pattern does not compile: {error}",
        }

    if outcome.correct:
        return 1.0, {"line": example.line, "feedback": "Captured the expected id."}

    expected = outcome.expected or "(nothing, this line has no request id)"
    captured = outcome.captured or "(nothing)"
    return 0.0, {
        "line": example.line,
        "expected": expected,
        "captured": captured,
        "feedback": f"Expected {expected} but captured {captured}.",
    }


def score(pattern: str, examples: tuple[LogLine, ...]) -> float:
    """Share of `examples` the pattern gets exactly right, 0.0 to 1.0."""
    if not examples:
        return 0.0
    return sum(evaluate(pattern, example)[0] for example in examples) / len(examples)


def report(pattern: str, examples: tuple[LogLine, ...] = LINES) -> list[Outcome]:
    """Every line and what the pattern did to it, wrong ones first."""
    try:
        outcomes = [judge(pattern, example) for example in examples]
    except PatternError as error:
        raise SystemExit(f"that pattern does not compile: {error}") from error
    return sorted(outcomes, key=lambda outcome: outcome.correct)


SPLITS: dict[str, tuple[LogLine, ...]] = {
    "train": TRAIN,
    "validation": VALIDATION,
    "held-out": HELD_OUT,
}
