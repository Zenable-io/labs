# Copyright (c) 2026 Zenable, Inc.

"""Unit tests for the Jev half of the lab, with no key and no network."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import dspy
import pytest
from dspylab import jev
from dspylab import program as lab
from dspylab.commits import TYPES

BASE_URL = "https://example.test"
ANSWERS = {
    "commit_type": {"choice": "docs", "confidence": 0.9, "probabilities": {"docs": 0.9}}
}


def request(subject: str = "a line") -> dict:
    return {
        "provider": "typesafe",
        "model": "jev-latest",
        "base_url": BASE_URL,
        "state": {"instructions": "classify", "inputs": {"subject": subject}},
        "questions": {"commit_type": {"type": "choice"}},
    }


def history_entry(cache_hit: bool, subject: str = "a line") -> dict:
    return {
        "request": request(subject),
        "response": {
            "model": "jev-2026",
            "usage": {"prompt_tokens": 12},
            "answers": ANSWERS,
        },
        "cache_hit": cache_hit,
    }


def fake_lm(*entries: dict) -> SimpleNamespace:
    return SimpleNamespace(model="jev-latest", base_url=BASE_URL, history=list(entries))


def write_fixture(path: Path, *subjects: str) -> None:
    saved = jev.recordings(fake_lm(*(history_entry(False, s) for s in subjects)))
    path.write_text(saved.model_dump_json())


@pytest.mark.unit
def test_jev_runs_the_local_programs_signature_unchanged() -> None:
    assert jev.build().signature.equals(lab.build().signature)


@pytest.mark.unit
def test_a_program_without_weights_leaves_every_type_at_one() -> None:
    assert jev.weights_of(jev.build()) == dict.fromkeys(TYPES, 1.0)


@pytest.mark.unit
def test_weights_land_where_reanchor_writes_them() -> None:
    module = jev.build({"docs": 2.0})
    assert module.fields == {"commit_type": {"weights": {"docs": 2.0}}}
    assert jev.weights_of(module)["docs"] == 2.0


@pytest.mark.unit
def test_probabilities_read_the_last_answer() -> None:
    assert jev.probabilities(fake_lm(history_entry(True))) == {"docs": 0.9}


@pytest.mark.unit
def test_sent_counts_only_answers_jev_gave() -> None:
    assert jev.sent(fake_lm(history_entry(False), history_entry(True))) == 1


@pytest.mark.unit
def test_recordings_keep_each_request_once_and_drop_usage() -> None:
    lm = fake_lm(
        history_entry(False), history_entry(True), history_entry(False, "other")
    )
    saved = jev.recordings(lm)
    assert (saved.model, saved.base_url) == ("jev-latest", BASE_URL)
    assert [
        item.request["state"]["inputs"]["subject"] for item in saved.recordings
    ] == [
        "a line",
        "other",
    ]
    assert "usage" not in json.loads(saved.model_dump_json())["recordings"][0]


@pytest.mark.unit
@pytest.mark.parametrize("asynchronous", [False, True])
def test_a_replay_answers_from_the_recording_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    path = tmp_path / "recorded.json"
    write_fixture(path, "a line")
    monkeypatch.setattr(jev, "FIXTURE_FILE", path)
    lm = jev.configure(fixtures=True)
    assert (lm.model, lm.base_url) == ("jev-latest", BASE_URL)
    assert dspy.cache.get(request())["answers"] == ANSWERS
    query = request()
    answer = (
        asyncio.run(lm.acall(query["state"], query["questions"]))
        if asynchronous
        else lm(query["state"], query["questions"])
    )
    assert answer == ANSWERS
    assert jev.sent(lm) == 0


@pytest.mark.unit
@pytest.mark.parametrize("asynchronous", [False, True])
def test_a_replay_names_the_line_it_has_no_recording_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    path = tmp_path / "recorded.json"
    write_fixture(path, "a line")
    monkeypatch.setattr(jev, "FIXTURE_FILE", path)
    lm = jev.configure(fixtures=True)
    unrecorded = request("a line nobody recorded")
    with pytest.raises(jev.FixtureMiss, match="a line nobody recorded"):
        if asynchronous:
            asyncio.run(lm.acall(unrecorded["state"], unrecorded["questions"]))
        else:
            lm(unrecorded["state"], unrecorded["questions"])


@pytest.mark.unit
def test_a_live_run_without_a_key_says_how_to_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="--fixtures"):
        jev.configure(fixtures=False)
