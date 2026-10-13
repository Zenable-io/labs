"""Copyright (c) 2026 Zenable, Inc. Fixture replay, which is the path these tests and the exercises share."""

import pytest
from jevlab.client import FixtureMiss, JevClient
from jevlab.questions import rank_questions, rubric_questions
from jevlab.subjects import REQUIREMENTS


def test_replay_answers_every_question_the_ranking_asked() -> None:
    client = JevClient(fixtures=True)
    answers = client.ask("rank:patch#1", {}, rank_questions("patch"))
    for requirement in REQUIREMENTS:
        assert 0.0 <= answers[f"governs::{requirement.name}"]["noul"] <= 1.0
        assert 0.0 <= answers[f"breaks::{requirement.name}"]["noul"] <= 1.0


def test_replay_carries_three_separate_passes_of_the_same_request() -> None:
    client = JevClient(fixtures=True)
    questions = rank_questions("patch")
    for index in (1, 2, 3):
        assert client.ask(f"rank:patch#{index}", {}, questions)


def test_replay_refuses_a_question_it_has_no_answer_for() -> None:
    client = JevClient(fixtures=True)
    edited = rank_questions("patch")
    edited["governs::jsonb-not-json"]["instructions"]["question"] = (
        "Is this a database file?"
    )
    with pytest.raises(FixtureMiss):
        client.ask("rank:patch#1", {}, edited)


def test_replay_keeps_the_two_readings_apart() -> None:
    client = JevClient(fixtures=True)
    quality = client.ask("grade:quality#1", {}, rubric_questions("quality"))
    risk = client.ask("grade:risk#1", {}, rubric_questions("risk"))
    assert quality != risk
    with pytest.raises(FixtureMiss):
        client.ask("grade:quality#1", {}, rubric_questions("risk"))
