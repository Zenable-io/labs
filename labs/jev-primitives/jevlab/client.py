"""Copyright (c) 2026 Zenable, Inc. One call to Jev, live or recorded.

Two code paths, on purpose. `--fixtures` replays answers recorded from a real
run so every exercise here works without a key, and the recorded answers are
looked up by the scenario name plus a fingerprint of the questions. Edit a
question and the fingerprint moves, so the replay stops instead of handing back
an answer to the question you used to be asking.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

FIXTURE_FILE = Path(__file__).resolve().parent / "fixtures" / "recorded.json"

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"


class Recording(BaseModel):
    """One recorded request and the answers it came back with."""

    model_config = ConfigDict(frozen=True, strict=False)

    scenario: str
    fingerprint: str
    model: str
    answers: dict[str, Any]


def fingerprint(questions: dict[str, Any]) -> str:
    """Identity of the questions, so a replay cannot answer an edited one."""
    payload = json.dumps(questions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


class FixtureMiss(RuntimeError):
    """No recording matches this scenario and these questions."""


class JevClient:
    """Asks Jev, or replays a recording of Jev.

    The live path reads `TYPESAFE_API_KEY` from the environment, and from the
    `~/.env` the sandbox exports into every login shell. Reading the file here
    too, on every construction, is what lets a key pasted in mid-session take
    effect on the next command instead of on the next terminal.
    """

    def __init__(self, *, fixtures: bool = False) -> None:
        load_dotenv(Path.home() / ".env", override=True)
        self.fixtures = fixtures
        self.base_url = os.environ.get("TYPESAFE_BASE_URL", DEFAULT_BASE_URL)
        self.model = os.environ.get("TYPESAFE_MODEL", DEFAULT_MODEL)
        self._recordings = _load_recordings() if fixtures else {}
        self._key = "" if fixtures else _require_key()

    def ask(
        self, scenario: str, state: Any, questions: dict[str, Any]
    ) -> dict[str, Any]:
        """Answers for every question, keyed the way they were asked."""
        if self.fixtures:
            recording = self._recordings.get((scenario, fingerprint(questions)))
            if recording is None:
                raise FixtureMiss(
                    f"no recording for {scenario!r} with these questions. "
                    "Set TYPESAFE_API_KEY and drop --fixtures to ask Jev."
                )
            return recording.answers

        response = httpx.post(
            f"{self.base_url}/v1/systemone",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"model": self.model, "state": state, "questions": questions},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["answers"]


def _require_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "TYPESAFE_API_KEY is not set. Put it in ~/.env, "
            "or pass --fixtures to replay recorded answers."
        )
    return key


def _load_recordings() -> dict[tuple[str, str], Recording]:
    if not FIXTURE_FILE.exists():
        return {}
    raw = json.loads(FIXTURE_FILE.read_text())
    recordings = [Recording.model_validate(item) for item in raw]
    return {(item.scenario, item.fingerprint): item for item in recordings}
