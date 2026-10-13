# Copyright (c) 2026 Zenable, Inc.

"""The reflection model the lab picks from what is in the environment."""

import pytest
from gepalab.__main__ import _reflection_model

KEYS = (
    "OPENROUTER_API_KEY",
    "ZENABLE_SANDBOX_MODEL",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "GEMINI_API_KEY",
)


@pytest.fixture(autouse=True)
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.unit
def test_a_sandbox_key_asks_openrouter_for_the_sandbox_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sandbox fills OPENAI_API_KEY with the same OpenRouter key.
    monkeypatch.setenv("OPENROUTER_API_KEY", "a-key")
    monkeypatch.setenv("OPENAI_API_KEY", "a-key")
    monkeypatch.setenv("ZENABLE_SANDBOX_MODEL", "anthropic/claude-haiku-4.5")
    assert _reflection_model(None) == "openrouter/anthropic/claude-haiku-4.5"


@pytest.mark.unit
def test_a_plain_openai_key_keeps_gepas_own_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "a-key")
    assert _reflection_model(None) == "openai/gpt-5.1"


@pytest.mark.unit
def test_an_explicit_model_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "a-key")
    monkeypatch.setenv("ZENABLE_SANDBOX_MODEL", "anthropic/claude-haiku-4.5")
    assert _reflection_model("gemini/gemini-2.5-pro") == "gemini/gemini-2.5-pro"


@pytest.mark.unit
def test_no_key_says_what_to_set() -> None:
    with pytest.raises(SystemExit, match="no reflection model"):
        _reflection_model(None)
