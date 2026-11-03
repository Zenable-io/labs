"""Copyright (c) 2026 Zenable, Inc. Scoring through one scorer, memoised, recorded and replayed."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from gepalab import classify, runs
from gepalab.classify import (
    SEED_PROMPT,
    FixtureMiss,
    Scorer,
    evaluate,
    parse_label,
    report,
    score,
    write_recordings,
)
from gepalab.triage import LINES, TRAIN, VALIDATION


def naive(prompt: str, line: str) -> str:
    """Answer by log level, the way the seed prompt tends to."""
    if "CRITICAL" in line or "ERROR" in line:
        return "page"
    if "WARN" in line:
        return "ticket"
    return "ignore"


@pytest.fixture
def scorer() -> Scorer:
    return classify.configure(Scorer(naive, model="test/model"))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("reply", "label"),
    [
        ("page", "page"),
        ("Ticket.", "ticket"),
        ("This is a ticket, nobody is paged.", "ticket"),
        ("I would IGNORE this one", "ignore"),
        ("pager duty", ""),
        ("", ""),
    ],
)
def test_the_first_label_in_a_reply_is_the_answer(reply: str, label: str) -> None:
    assert parse_label(reply) == label


@pytest.mark.unit
def test_feedback_carries_the_reason_whether_right_or_wrong(scorer: Scorer) -> None:
    retried = next(item for item in TRAIN if "retry 2 of 3 succeeded" in item.line)
    value, info = evaluate(SEED_PROMPT, retried)
    assert value == 0.0
    assert info["expected"] == "ignore"
    assert info["answered"] == "page"
    assert retried.reason in info["feedback"]

    routine = next(item for item in LINES if item.line.startswith("INFO  billing"))
    value, info = evaluate(SEED_PROMPT, routine)
    assert value == 1.0
    assert routine.reason in info["feedback"]


@pytest.mark.unit
def test_a_reply_with_no_label_scores_zero_and_says_so(scorer: Scorer) -> None:
    scorer.answers[(SEED_PROMPT, LINES[0].line)] = "I cannot tell."
    value, info = evaluate(SEED_PROMPT, LINES[0])
    assert value == 0.0
    assert info["answered"] == "(no label)"


@pytest.mark.unit
def test_the_scorer_asks_once_per_prompt_and_line(scorer: Scorer) -> None:
    assert score(SEED_PROMPT, VALIDATION) == score(SEED_PROMPT, VALIDATION)
    assert scorer.calls == len(VALIDATION)
    assert score(" " + SEED_PROMPT + "\n", VALIDATION) > 0
    assert scorer.calls == len(VALIDATION)


@pytest.mark.unit
def test_report_puts_the_wrong_lines_first(scorer: Scorer) -> None:
    correctness = [outcome.correct for outcome in report(SEED_PROMPT)]
    assert correctness == sorted(correctness)
    assert 0 < sum(correctness) < len(correctness)


@pytest.mark.unit
def test_a_live_scorer_sends_the_prompt_as_system_and_the_line_as_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, object]] = []

    def completion(**kwargs: object) -> SimpleNamespace:
        sent.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ticket"))]
        )

    monkeypatch.setattr(classify.litellm, "completion", completion)
    live = Scorer.live("openrouter/some/model")
    assert live.classify("Label it.", "WARN something") == "ticket"
    assert sent[0]["model"] == "openrouter/some/model"
    assert sent[0]["temperature"] == 0
    assert sent[0]["messages"] == [
        {"role": "system", "content": "Label it."},
        {"role": "user", "content": "WARN something"},
    ]


@pytest.mark.unit
def test_recordings_round_trip_and_replay_refuses_a_new_question(
    scorer: Scorer, tmp_path: Path
) -> None:
    score(SEED_PROMPT, VALIDATION)
    path = tmp_path / "fixtures" / "recorded.json"
    write_recordings(scorer.recordings(("```\nnew prompt\n```",)), path)
    assert path.with_name("recorded.json.license").read_text().startswith("Copyright")
    text = path.read_text()
    assert "usage" not in text and "cost" not in text

    replay = classify.configure(Scorer.replay(path))
    assert replay.model == "test/model"
    assert score(SEED_PROMPT, VALIDATION) == score(SEED_PROMPT, VALIDATION)
    assert replay.calls == 0
    with pytest.raises(FixtureMiss, match="no recorded answer"):
        evaluate("a prompt nobody recorded", VALIDATION[0])


@pytest.mark.unit
def test_replay_without_a_recording_says_how_to_make_one(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="gepalab record"):
        Scorer.replay(tmp_path / "missing.json")


@pytest.mark.unit
def test_a_saved_run_round_trips(scorer: Scorer, tmp_path: Path) -> None:
    class FakeResult:
        best_candidate = "Classify it. Retried errors are ignore."
        candidates = [
            {"current_candidate": SEED_PROMPT},
            {"current_candidate": best_candidate},
        ]
        val_aggregate_scores = [0.5, 0.75]
        total_metric_calls = 42

    path = tmp_path / "run" / "run.json"
    saved = runs.save(FakeResult(), path, seed=SEED_PROMPT, model="test/model")
    again = runs.load(path)
    assert again == saved
    assert again.evaluations == 42
    assert again.seed_scores["train"] == score(SEED_PROMPT, TRAIN)


@pytest.mark.unit
def test_loading_a_run_that_is_not_there_explains_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        runs.load(tmp_path / "missing.json")
    assert "evolve" in str(error.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "options"),
    [
        (
            "openrouter/anthropic/claude-haiku-5.5",
            {"extra_body": {"reasoning": {"enabled": False}}},
        ),
        ("openai/gpt-5.4-nano", {"reasoning_effort": "none"}),
        ("gemini/gemini-3.5-flash-lite", {}),
    ],
)
def test_no_thinking_keeps_the_output_cap_for_the_answer(
    model: str, options: dict
) -> None:
    assert classify.no_thinking(model) == options
