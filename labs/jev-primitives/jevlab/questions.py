"""Copyright (c) 2026 Zenable, Inc. Every question this rig asks, in one file.

Jev answers the question as written, literally, so the wording here is the
policy. Keeping it together means a change to a criterion is a change to a file
somebody reviews, rather than a string edited at a call site.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict

from jevlab.levels import READINGS
from jevlab.subjects import ENGINES, REQUIREMENTS


class Dimension(BaseModel):
    """One named axis a subject is graded along."""

    model_config = ConfigDict(frozen=True, strict=True)

    name: str
    definition: str


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        name="testability",
        definition=(
            "Whether a reviewer could decide, from the statement alone and with "
            "no other conversation, that a given change does or does not satisfy it."
        ),
    ),
    Dimension(
        name="specificity",
        definition=(
            "Whether the statement names the exact condition it requires, rather "
            "than a quality the author would like the code to have."
        ),
    ),
    Dimension(
        name="scope",
        definition=(
            "Whether the statement says which code it applies to, so a reader "
            "can tell whether a file is in or out of its reach."
        ),
    ),
)

CHOICE_OPTIONS: dict[str, str] = {
    "full": (
        "Every condition the requirement states can be expressed as a check this "
        "engine runs. A change that satisfies the check satisfies the requirement."
    ),
    "partial": (
        "Some of what the requirement states can be expressed as a check this "
        "engine runs, and some of it cannot. A change that passes the check may "
        "still break the requirement."
    ),
    "none": (
        "Nothing the requirement states can be expressed as a check this engine "
        "runs, because the engine does not read this kind of file or cannot see "
        "the condition the requirement names."
    ),
}

_GOVERNS_BY_PATCH = (
    "Does `requirements.{name}.statement` govern code of the kind the changed "
    "lines in `file.patch` touch?"
)

_GOVERNS_BY_FILE = (
    "Does `requirements.{name}.statement` govern code of the kind `file.content` "
    "contains?"
)

_BREAKS = "Do the changed lines in `file.patch` break `requirements.{name}.statement`?"


def rank_questions(anchor: str) -> dict[str, Any]:
    """Two Nouls per requirement, all in one request.

    Jev evaluates every question in a request against the state in parallel, so
    twelve questions here cost one round trip and the tokens of the extra
    question text.
    """
    governs = _GOVERNS_BY_FILE if anchor == "file" else _GOVERNS_BY_PATCH
    questions: dict[str, Any] = {}
    for requirement in REQUIREMENTS:
        questions[f"governs::{requirement.name}"] = {
            "type": "noul",
            "instructions": {
                "question": governs.format(name=requirement.name),
                "focus": (
                    "Judge the kind of code, not whether this particular change "
                    "happens to break the rule."
                ),
            },
            "criteria": {
                "true": "The requirement has something to say about this code.",
                "false": "The requirement has nothing to say about this code.",
            },
        }
        questions[f"breaks::{requirement.name}"] = {
            "type": "noul",
            "instructions": {
                "question": _BREAKS.format(name=requirement.name),
                "focus": "Judge only the added and removed lines, not the rest of the file.",
            },
            "criteria": {
                "true": "The changed lines contradict the requirement.",
                "false": "The changed lines are consistent with the requirement.",
            },
        }
    return questions


def engine_choice_questions(requirement_name: str) -> dict[str, Any]:
    """One Choice per engine, over how much of the requirement it can check."""
    return {
        engine.name: {
            "type": "choice",
            "instructions": {
                "question": (
                    f"How much of `requirement.statement` can a guardrail written "
                    f"for `engines.{engine.name}` check?"
                ),
                "focus": (
                    f"Judge against `engines.{engine.name}.capabilities`. A "
                    f"condition the engine cannot see is a condition it cannot check."
                ),
            },
            "criteria": dict(CHOICE_OPTIONS),
        }
        for engine in ENGINES
    }


def engine_noul_questions(requirement_name: str) -> dict[str, Any]:
    """The same judgment as one probability per engine, for comparison."""
    return {
        engine.name: {
            "type": "noul",
            "instructions": {
                "question": (
                    f"Can a guardrail written for `engines.{engine.name}` check "
                    f"`requirement.statement`?"
                ),
                "focus": f"Judge against `engines.{engine.name}.capabilities`.",
            },
            "criteria": {
                "true": "The engine can check the requirement.",
                "false": "The engine cannot check the requirement.",
            },
        }
        for engine in ENGINES
    }


def rubric_questions(reading: str) -> dict[str, Any]:
    """One Score per dimension, over the level set the reading selects."""
    framing, levels = READINGS[reading]
    return {
        dimension.name: {
            "type": "score",
            "instructions": {
                "question": (
                    f"Against the definition of `{dimension.name}`, which level "
                    f"best describes `candidate.statement`?"
                ),
                "dimension": dimension.definition,
                "reading": framing,
            },
            "criteria": list(levels),
        }
        for dimension in DIMENSIONS
    }
