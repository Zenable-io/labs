"""Copyright (c) 2026 Zenable, Inc. The parts of the rig that decide things, tested without a network."""

import pytest
from jevlab.client import fingerprint
from jevlab.levels import ANCHORS, rubric_score
from jevlab.questions import (
    CHOICE_OPTIONS,
    DIMENSIONS,
    engine_choice_questions,
    engine_noul_questions,
    rank_questions,
    rubric_questions,
)
from jevlab.subjects import ENGINES, REQUIREMENTS


def test_one_request_packs_two_questions_per_requirement() -> None:
    questions = rank_questions("patch")
    assert len(questions) == 2 * len(REQUIREMENTS)
    for requirement in REQUIREMENTS:
        assert f"governs::{requirement.name}" in questions
        assert f"breaks::{requirement.name}" in questions


def test_the_anchor_changes_the_question_and_leaves_everything_else_alone() -> None:
    by_patch = rank_questions("patch")
    by_file = rank_questions("file")
    changed = [key for key in by_patch if by_patch[key] != by_file[key]]
    assert changed == [f"governs::{requirement.name}" for requirement in REQUIREMENTS]


def test_a_reworded_criterion_is_a_different_question() -> None:
    before = fingerprint(rank_questions("patch"))
    widened = rank_questions("patch")
    widened["governs::jsonb-not-json"]["criteria"]["true"] = "anything at all"
    assert fingerprint(widened) != before


def test_every_choice_option_carries_a_description() -> None:
    questions = engine_choice_questions("money-as-minor-units")
    assert set(questions) == {engine.name for engine in ENGINES}
    for question in questions.values():
        assert set(question["criteria"]) == set(CHOICE_OPTIONS)
        assert all(question["criteria"].values())


def test_the_noul_shape_asks_one_question_per_engine() -> None:
    questions = engine_noul_questions("money-as-minor-units")
    assert {question["type"] for question in questions.values()} == {"noul"}


@pytest.mark.parametrize("reading", ("quality", "risk"))
def test_a_reading_selects_the_level_text_and_nothing_else(reading: str) -> None:
    questions = rubric_questions(reading)
    assert set(questions) == {dimension.name for dimension in DIMENSIONS}
    for dimension in DIMENSIONS:
        question = questions[dimension.name]
        assert question["instructions"]["dimension"] == dimension.definition
        assert len(question["criteria"]) == len(ANCHORS)


def test_the_two_readings_differ_only_in_their_level_text() -> None:
    quality = rubric_questions("quality")
    risk = rubric_questions("risk")
    for name, question in quality.items():
        assert (
            question["instructions"]["question"]
            == risk[name]["instructions"]["question"]
        )
        assert question["criteria"] != risk[name]["criteria"]


def test_a_score_is_re_weighted_over_the_anchors_not_read_off_the_level() -> None:
    all_on_level_one = rubric_score({0: 0.0, 1: 1.0, 2: 0.0, 3: 0.0, 4: 0.0})
    assert all_on_level_one == ANCHORS[1]
    split = rubric_score({0: 0.0, 1: 0.5, 2: 0.5, 3: 0.0, 4: 0.0})
    assert split == pytest.approx((ANCHORS[1] + ANCHORS[2]) / 2)
