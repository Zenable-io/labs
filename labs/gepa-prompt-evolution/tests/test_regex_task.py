"""Copyright (c) 2026 Zenable, Inc. Unit tests for the scoring side of the lab, which never calls a model."""

import pytest
from gepalab import runs
from gepalab.loglines import HELD_OUT, LINES, TRAIN, VALIDATION
from gepalab.regex_task import (
    SEED_PATTERN,
    PatternError,
    capture,
    evaluate,
    report,
    score,
)


def test_every_line_lands_in_exactly_one_split() -> None:
    splits = [TRAIN, VALIDATION, HELD_OUT]
    assert sum(len(split) for split in splits) == len(LINES)
    seen = [line.line for split in splits for line in split]
    assert len(set(seen)) == len(LINES)


def test_no_split_can_be_won_by_matching_nothing() -> None:
    for split in (TRAIN, VALIDATION, HELD_OUT):
        empty = [line for line in split if not line.request_id]
        assert empty, "a split with no unlabelled line makes 'never match' look good"
        assert len(empty) < len(split)


def test_a_named_group_wins_over_the_first_group() -> None:
    assert capture(r"(trace=\w+).*(?P<id>8f\w+)", "trace=aa req 8f21ad") == "8f21ad"


def test_the_whole_match_is_used_when_there_are_no_groups() -> None:
    assert capture(r"8f\w+", "req 8f21ad here") == "8f21ad"


def test_a_pattern_that_finds_nothing_captures_the_empty_string() -> None:
    assert capture(r"nothing_like_this", "req_id=8f21ad") == ""


def test_a_pattern_that_does_not_compile_is_refused() -> None:
    with pytest.raises(PatternError):
        capture(r"req_id=(", "req_id=8f21ad")


def test_a_broken_pattern_scores_zero_and_says_why() -> None:
    result, info = evaluate(r"req_id=(", LINES[0])
    assert result == 0.0
    assert "does not compile" in info["feedback"]


def test_feedback_names_both_sides_of_a_miss() -> None:
    line = next(item for item in LINES if item.request_id == "8f21ae")
    result, info = evaluate(SEED_PATTERN, line)
    assert result == 0.0
    assert info["expected"] == "8f21ae"
    assert info["captured"] == "(nothing)"


def test_the_seed_is_right_about_some_of_it_and_not_all_of_it() -> None:
    for split in (TRAIN, VALIDATION, HELD_OUT):
        assert 0.0 < score(SEED_PATTERN, split) < 1.0


def test_report_puts_the_wrong_lines_first() -> None:
    outcomes = report(SEED_PATTERN)
    correctness = [outcome.correct for outcome in outcomes]
    assert correctness == sorted(correctness)


def test_a_saved_run_round_trips(tmp_path) -> None:
    class FakeResult:
        best_candidate = r"req_id=(?P<id>\S+)"
        candidates = [
            {"current_candidate": SEED_PATTERN},
            {"current_candidate": best_candidate},
        ]
        val_aggregate_scores = [0.5, 0.75]
        total_metric_calls = 42

    path = tmp_path / "run" / "run.json"
    saved = runs.save(FakeResult(), path, seed=SEED_PATTERN, model="test/model")
    again = runs.load(path)
    assert again == saved
    assert again.evaluations == 42
    assert again.seed_scores["train"] == score(SEED_PATTERN, TRAIN)


def test_loading_a_run_that_is_not_there_explains_what_to_do(tmp_path) -> None:
    with pytest.raises(SystemExit) as error:
        runs.load(tmp_path / "missing.json")
    assert "evolve" in str(error.value)
