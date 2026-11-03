# Copyright (c) 2026 Zenable, Inc.

"""The model the lab picks from the environment, and a recorded run replaying without a provider."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from gepalab import __main__ as cli
from gepalab import classify, steps
from gepalab.__main__ import _live_model
from gepalab.runs import load
from gepalab.triage import LINES

KEYS = (
    "OPENROUTER_API_KEY",
    "ZENABLE_SANDBOX_MODEL",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "GEMINI_API_KEY",
)

TRUTH = {item.line: item.label for item in LINES}

GOOD_PROMPT = (
    "Classify this log line as page, ticket, or ignore. An error that retried "
    "and succeeded is ignore."
)
REFLECTIONS = (
    f"Here is a better prompt:\n```\n{GOOD_PROMPT}\n```",
    f"```text\n{GOOD_PROMPT} Deprecations are ticket.\n```",
    f"```\n{GOOD_PROMPT} Draining nodes are ignore.\n```",
)


def fake_ask(model: str, prompt: str, line: str) -> str:
    """Right once the prompt mentions retries, otherwise by log level."""
    if "retried" in prompt:
        return TRUTH[line]
    if "CRITICAL" in line or "ERROR" in line:
        return "page"
    return "ignore"


@pytest.fixture(autouse=True)
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: None)


@pytest.fixture
def fixtures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Fixtures recorded through the real `record` path, from a fake provider."""
    fixture_dir = tmp_path / "fixtures"
    monkeypatch.setattr(cli, "FIXTURE_DIR", fixture_dir)
    monkeypatch.setattr(cli, "_live_model", lambda requested: "fake/model")
    monkeypatch.setattr(classify, "ask", fake_ask)
    replies = iter(REFLECTIONS)

    def completion(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))]
        )

    monkeypatch.setattr(steps.litellm, "completion", completion)
    assert cli.main(["record", "--out", str(tmp_path / "record")]) == 0
    assert (fixture_dir / "recorded.json.license").is_file()
    assert (fixture_dir / "recorded_run.json.license").is_file()

    def no_provider(*args: object, **kwargs: object) -> str:
        pytest.fail("Replay must never call a provider")

    monkeypatch.setattr(classify, "ask", no_provider)
    monkeypatch.setattr(steps.litellm, "completion", no_provider)
    monkeypatch.setattr(cli, "_live_model", no_provider)
    return fixture_dir


@pytest.mark.unit
def test_a_sandbox_key_asks_openrouter_for_the_sandbox_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sandbox fills OPENAI_API_KEY with the same OpenRouter key.
    monkeypatch.setenv("OPENROUTER_API_KEY", "a-key")
    monkeypatch.setenv("OPENAI_API_KEY", "a-key")
    monkeypatch.setenv("ZENABLE_SANDBOX_MODEL", "anthropic/claude-haiku-4.5")
    assert _live_model(None) == "openrouter/anthropic/claude-haiku-4.5"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "model"),
    [
        ("OPENROUTER_API_KEY", "openrouter/google/gemini-2.5-flash-lite"),
        ("OPENAI_API_KEY", "openai/gpt-5.4-nano"),
        ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5-20251001"),
        ("CLAUDE_API_KEY", "anthropic/claude-haiku-4-5-20251001"),
        ("GEMINI_API_KEY", "gemini/gemini-3.5-flash-lite"),
    ],
)
def test_provider_keys_select_lightweight_models(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    model: str,
) -> None:
    monkeypatch.setenv(key, "a-key")
    assert _live_model(None) == model


@pytest.mark.unit
def test_an_explicit_model_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "a-key")
    monkeypatch.setenv("ZENABLE_SANDBOX_MODEL", "anthropic/claude-haiku-4.5")
    assert _live_model("gemini/gemini-2.5-pro") == "gemini/gemini-2.5-pro"


@pytest.mark.unit
def test_no_key_says_what_to_set() -> None:
    with pytest.raises(SystemExit, match="no model is configured"):
        _live_model(None)


@pytest.mark.unit
@pytest.mark.parametrize(
    "option",
    [
        "--budget",
        "--refinements",
        "--concurrency",
        "--reflect-on",
        "--reflection-tokens",
    ],
)
def test_nonpositive_limits_fail_before_a_model_is_selected(option: str) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["evolve", option, "0"])
    assert error.value.code == 2


@pytest.mark.unit
def test_live_defaults_bound_proposals_and_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "a-key")

    def inspect_config(*args: object, **kwargs: object) -> None:
        config = kwargs["config"]
        assert isinstance(config, cli.GEPAConfig)
        assert config.engine.max_candidate_proposals == 3
        assert config.engine.max_workers == 4
        assert config.engine.max_metric_calls == 96
        assert config.engine.frontier_type == "instance"
        assert config.reflection.reflection_minibatch_size == 4
        reflection = config.reflection.reflection_lm
        assert isinstance(reflection, steps.LiveReflection)
        assert reflection.model == "openai/gpt-5.4-nano"
        assert reflection.kwargs == {
            "max_tokens": 1024,
            "num_retries": 0,
            "reasoning_effort": "none",
        }
        raise SystemExit(0)

    monkeypatch.setattr(cli, "optimize_anything", inspect_config)
    with pytest.raises(SystemExit) as error:
        cli.main(["evolve", "--out", str(tmp_path / "live")])
    assert error.value.code == 0


@pytest.mark.integration
@pytest.mark.parametrize("refinements", [1, 3])
def test_replay_runs_real_gepa_without_a_provider(
    fixtures: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    refinements: int,
) -> None:
    output = tmp_path / "replay"
    assert (
        cli.main(
            [
                "evolve",
                "--fixtures",
                "--refinements",
                str(refinements),
                "--out",
                str(output),
            ]
        )
        == 0
    )
    captured = capsys.readouterr().out
    assert captured.count("proposed prompt:") == refinements
    assert "model calls" not in captured
    saved = load(output / "run.json")
    assert saved.model == cli.REPLAY
    assert saved.best_candidate == GOOD_PROMPT
    assert saved.scores["validation"] > saved.seed_scores["validation"]
    assert saved.scores["held-out"] == 1.0
    assert (output / "optimizer.log").is_file()


@pytest.mark.integration
def test_quit_stops_before_the_next_reflection(
    fixtures: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "q")
    assert (
        cli.main(["evolve", "--fixtures", "--pause", "--out", str(tmp_path / "paused")])
        == 0
    )
    assert capsys.readouterr().out.count("proposed prompt:") == 1


@pytest.mark.integration
def test_every_replay_step_of_the_lab_answers_from_the_recording(
    fixtures: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["baseline", "--fixtures", "--misses", "2"]) == 0
    baseline = capsys.readouterr().out
    assert "exact-match score by split" in baseline
    assert "lines are still wrong, the first 2" in baseline
    assert "model calls" not in baseline

    assert cli.main(["feedback", "--fixtures"]) == 0
    assert "expected: ignore" in capsys.readouterr().out

    assert cli.main(["select", "--fixtures", "--seed", "0"]) == 0
    assert "Sampled parent:" in capsys.readouterr().out

    assert cli.main(["merge", "--fixtures"]) == 0
    assert "Same training minibatch:" in capsys.readouterr().out

    assert cli.main(["show", "--lineage"]) == 0
    shown = capsys.readouterr().out
    assert "scored with fake/model" in shown
    assert "  1. [" in shown


@pytest.mark.unit
def test_a_replay_miss_fails_loudly(
    fixtures: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["score", "--fixtures", "a prompt nobody recorded"]) == 2
    assert "fixture miss" in capsys.readouterr().err


@pytest.mark.unit
def test_replay_without_fixtures_says_how_to_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "FIXTURE_DIR", tmp_path)
    with pytest.raises(SystemExit, match="gepalab record"):
        cli.main(["baseline", "--fixtures"])


@pytest.mark.unit
def test_existing_search_is_not_resumed_or_overwritten(
    fixtures: Path, tmp_path: Path
) -> None:
    (tmp_path / "gepa").mkdir()
    with pytest.raises(SystemExit, match="fresh --out"):
        cli.main(["evolve", "--fixtures", "--out", str(tmp_path)])
