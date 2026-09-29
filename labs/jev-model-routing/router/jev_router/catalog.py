"""Copyright (c) 2026 Zenable, Inc. The model catalogue, and the routing question written over it.

The criteria text IS the routing policy. Jev answers the question as written,
literally, so widening one option's description is a policy change, and it
lives in `policy.json` beside this module where a diff of a proposed edit is a
diff of the policy rather than a diff of the program that sends it.

`jev_router.align` writes that file from an accepted jev-align run, so an
aligned definition reaches the router the same way a hand edit does.
"""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

POLICY_FILE = Path(__file__).resolve().parent / "policy.json"


class CandidateModel(BaseModel):
    """One model agentgateway can route to, and the case for choosing it."""

    model_config = ConfigDict(frozen=True, strict=True)

    name: str
    """The name in `llm.models[].name`. Jev returns this string verbatim."""

    criterion: str
    """What kind of request belongs on this model. Read literally by Jev."""


class RoutingPolicy(BaseModel):
    """Everything about the question this router asks, as one reviewable object."""

    model_config = ConfigDict(frozen=True, strict=True)

    question: str

    focus: str = ""
    """A second field Jev reads as part of the same instructions. An aligned
    policy usually arrives as one block of instructions and leaves this empty,
    which is a different question from the one with it and fingerprints as one."""

    models: tuple[CandidateModel, ...]
    """Ordered cheapest first. The order is not a tie-break: Jev returns a full
    distribution and the caller takes the argmax. It decides the fallback."""


def load_policy(path: Path = POLICY_FILE) -> RoutingPolicy:
    return RoutingPolicy.model_validate_json(path.read_text())


POLICY: RoutingPolicy = load_policy()

CATALOG: tuple[CandidateModel, ...] = POLICY.models

MODEL_NAMES: frozenset[str] = frozenset(model.name for model in CATALOG)

QUESTION_ID = "route"

QUESTION_TEXT = POLICY.question

QUESTION_FOCUS = POLICY.focus


def build_questions() -> dict[str, object]:
    """The `questions` block of a `/v1/systemone` request."""
    instructions: dict[str, str] = {"question": QUESTION_TEXT}
    if QUESTION_FOCUS:
        instructions["focus"] = QUESTION_FOCUS
    return {
        QUESTION_ID: {
            "type": "choice",
            "instructions": instructions,
            "criteria": {model.name: model.criterion for model in CATALOG},
        }
    }


def policy_fingerprint(jev_model: str) -> str:
    """Identity of everything that can change a routing answer but the request.

    Every cache entry is keyed under this, so editing a criterion, the question,
    the candidate set, or the Jev model id invalidates the whole cache at once.
    A TTL cannot do that: the stale entries would outlive the policy that
    produced them for as long as the TTL runs.
    """
    payload = json.dumps(
        {"jev_model": jev_model, "questions": build_questions()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
