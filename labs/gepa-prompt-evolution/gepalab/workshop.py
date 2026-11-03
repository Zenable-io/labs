# Copyright (c) 2026 Zenable, Inc.

"""Small exercises for selection and component merging, on prepared prompts.

A prompt here is two components, the way a larger system has one prompt per
module: `definitions` says what each label means, `rules` covers the lines a
definition alone gets wrong. Each prepared candidate improves one of them.
"""

import random

from gepa.gepa_utils import (
    remove_dominated_programs,
    select_program_candidate_from_pareto_front,
)
from pydantic import BaseModel, ConfigDict

from gepalab.classify import SEED_PROMPT, evaluate, score
from gepalab.triage import TRAIN, VALIDATION


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    name: str
    definitions: str
    rules: str
    parent: str | None = None

    @property
    def prompt(self) -> str:
        return "\n\n".join(part for part in (self.definitions, self.rules) if part)


SEED = Candidate(name="seed", definitions=SEED_PROMPT, rules="")
DEFINITIONS = SEED.model_copy(
    update={
        "name": "definitions",
        "parent": SEED.name,
        "definitions": (
            "Classify this log line for on-call triage. Answer with one word.\n"
            "page: customers are affected now, or will be within hours, and a "
            "person has to act.\n"
            "ticket: a real problem that can wait for the next working day.\n"
            "ignore: nothing for a person to do."
        ),
    }
)
RULES = SEED.model_copy(
    update={
        "name": "rules",
        "parent": SEED.name,
        "rules": (
            "House rules come first. Anything from staging, canary or a load "
            "test is ignore, however severe. Any error on the payments path "
            "(payments, checkout, refunds, the ledger) is page, even when a "
            "retry succeeded. Any access or identity change, such as a new "
            "credential, a role grant or a bucket policy, is page whatever the "
            "log level says."
        ),
    }
)
CANDIDATES = (SEED, DEFINITIONS, RULES)
MERGE_BATCH = (TRAIN[0], TRAIN[2], TRAIN[6])
"""Three training lines: a staging alarm, a retried error and a deprecation notice."""


def selection_front(candidates: tuple[Candidate, ...]) -> dict[int, set[int]]:
    scores = [
        [evaluate(candidate.prompt, example)[0] for example in VALIDATION]
        for candidate in candidates
    ]
    front = {
        index: {
            candidate_index
            for candidate_index, row in enumerate(scores)
            if row[index] == max(other[index] for other in scores)
        }
        for index in range(len(VALIDATION))
    }
    return remove_dominated_programs(
        front,
        scores=[sum(row) / len(row) for row in scores],
    )


def select(seed: int) -> Candidate:
    aggregates = [score(candidate.prompt, VALIDATION) for candidate in CANDIDATES]
    front = selection_front(CANDIDATES)
    eligible = set().union(*front.values())
    print("Validation scores for three prepared candidates:")
    for index, candidate in enumerate(CANDIDATES):
        status = "available for sampling" if index in eligible else "dominated"
        print(f"  {candidate.name:<12} {aggregates[index]:>6.1%}  {status}")
    index = select_program_candidate_from_pareto_front(
        front,
        aggregates,
        random.Random(seed),
    )
    selected = CANDIDATES[index]
    print(f"\nSampled parent: {selected.name}")
    lower, higher = sorted(
        (DEFINITIONS, RULES), key=lambda item: score(item.prompt, VALIDATION)
    )
    only_lower = [
        example
        for example in VALIDATION
        if evaluate(lower.prompt, example)[0] > evaluate(higher.prompt, example)[0]
    ]
    if only_lower:
        print(f"\nA line {lower.name} gets right and {higher.name} misses:")
        print(f"  {only_lower[0].line}")
    else:
        print(
            f"\nNo validation line is right under {lower.name} and wrong under {higher.name}."
        )
    return selected


def merge(ancestor: Candidate, left: Candidate, right: Candidate) -> Candidate:
    if left.parent != ancestor.name or right.parent != ancestor.name:
        raise ValueError("Both candidates must share the supplied ancestor.")
    components = ("definitions", "rules")
    left_changes = {
        name for name in components if getattr(left, name) != getattr(ancestor, name)
    }
    right_changes = {
        name for name in components if getattr(right, name) != getattr(ancestor, name)
    }
    if not left_changes or not right_changes or left_changes & right_changes:
        raise ValueError("This exercise merges improvements to different components.")
    updates = {name: getattr(left, name) for name in left_changes}
    updates.update({name: getattr(right, name) for name in right_changes})
    return ancestor.model_copy(
        update={"name": "merged", "parent": ancestor.name, **updates}
    )


def show_merge() -> None:
    candidate = merge(SEED, DEFINITIONS, RULES)
    print("Common ancestor: seed")
    print("  definitions changed the definitions component")
    print("  rules changed the rules component")
    print("\nSame training minibatch:")
    batch_scores = {
        item.name: score(item.prompt, MERGE_BATCH)
        for item in (DEFINITIONS, RULES, candidate)
    }
    for name, value in batch_scores.items():
        print(f"  {name:<12} {value:>6.1%}")
    if batch_scores["merged"] <= max(
        batch_scores["definitions"], batch_scores["rules"]
    ):
        print("\nNo improvement on the minibatch; GEPA would discard this merge.")
        return
    print("\nImproved; evaluate on the larger validation set:")
    print(
        f"  {len(VALIDATION)} lines, {score(candidate.prompt, VALIDATION):.1%} exact matches"
    )
    print(f"\nMerged prompt:\n{candidate.prompt}")
