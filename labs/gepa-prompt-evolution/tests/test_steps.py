"""Copyright (c) 2026 Zenable, Inc. What a refinement prints about the feedback reflection reads."""

from pathlib import Path

import pytest
from gepalab.steps import FEEDBACK_CHARS, StepObserver


@pytest.mark.unit
def test_each_feedback_prints_on_one_bounded_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    observer = StepObserver(log_path=tmp_path / "log", pause=False, refinements=1)
    short = "Correct, ignore: The purge completed on retry."
    long = "Expected page, answered ticket. " + "x" * FEEDBACK_CHARS
    observer.on_reflective_dataset_built(
        {"dataset": {"current_candidate": [{"feedback": short}, {"feedback": long}]}}
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == f"    - {short}"
    assert len(lines[2]) == len("    - ") + FEEDBACK_CHARS
    assert lines[2].endswith("…")
