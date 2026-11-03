# Copyright (c) 2026 Zenable, Inc.

"""Selection and merging use per-example outcomes from the configured scorer."""

import pytest
from gepalab import classify
from gepalab.classify import Scorer, score
from gepalab.triage import LINES, VALIDATION
from gepalab.workshop import (
    CANDIDATES,
    DEFINITIONS,
    MERGE_BATCH,
    RULES,
    SEED,
    merge,
    select,
    selection_front,
    show_merge,
)

TRUTH = {item.line: item.label for item in LINES}


def specialist(prompt: str, line: str) -> str:
    """Right wherever the prompt carries the component a line needs, naive elsewhere.

    Lines under a house rule follow the rules component and get `ticket`, wrong
    for every one of them, without it; the rest follow the definitions component.
    """
    needs_rules = any(
        word in line
        for word in (
            "staging",
            "canary",
            "loadtest",
            "payments",
            "checkout",
            "refunds",
            "iam ",
            "admin role",
            "public-read",
        )
    )
    if needs_rules:
        return TRUTH[line] if "staging" in prompt else "ticket"
    return TRUTH[line] if "ticket:" in prompt else "ignore"


@pytest.fixture(autouse=True)
def scorer() -> Scorer:
    return classify.configure(Scorer(specialist, model="test/model"))


@pytest.mark.unit
def test_selection_keeps_both_specialists_and_removes_the_seed() -> None:
    front = selection_front(CANDIDATES)
    assert set().union(*front.values()) == {1, 2}
    assert score(RULES.prompt, VALIDATION) < score(DEFINITIONS.prompt, VALIDATION)
    assert select(0) in (DEFINITIONS, RULES)


@pytest.mark.unit
def test_merge_combines_disjoint_changes_and_improves_the_same_minibatch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = merge(SEED, DEFINITIONS, RULES)
    assert candidate.definitions == DEFINITIONS.definitions
    assert candidate.rules == RULES.rules
    assert candidate.prompt == DEFINITIONS.definitions + "\n\n" + RULES.rules
    assert score(candidate.prompt, MERGE_BATCH) > max(
        score(parent.prompt, MERGE_BATCH) for parent in (DEFINITIONS, RULES)
    )
    show_merge()
    assert "Improved; evaluate on the larger validation set" in capsys.readouterr().out


@pytest.mark.unit
def test_a_merge_that_does_not_improve_is_reported_not_raised(
    capsys: pytest.CaptureFixture[str],
) -> None:
    classify.configure(Scorer(lambda prompt, line: "page", model="test/model"))
    show_merge()
    assert "GEPA would discard this merge" in capsys.readouterr().out


@pytest.mark.unit
def test_merge_refuses_unrelated_candidates() -> None:
    unrelated = RULES.model_copy(update={"parent": "another-seed"})
    with pytest.raises(ValueError, match="share"):
        merge(SEED, DEFINITIONS, unrelated)


@pytest.mark.unit
def test_merge_refuses_conflicting_component_changes() -> None:
    conflict = DEFINITIONS.model_copy(update={"name": "another-definitions"})
    with pytest.raises(ValueError, match="different components"):
        merge(SEED, DEFINITIONS, conflict)
