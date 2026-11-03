"""Copyright (c) 2026 Zenable, Inc. The dataset's shape, which every score in the lab depends on."""

import pytest
from gepalab.triage import HELD_OUT, LABELS, LINES, TRAIN, VALIDATION


@pytest.mark.unit
def test_every_line_lands_in_exactly_one_split() -> None:
    splits = [TRAIN, VALIDATION, HELD_OUT]
    assert [len(split) for split in splits] == [20, 12, 8]
    assert sum(len(split) for split in splits) == len(LINES)
    seen = [line.line for split in splits for line in split]
    assert len(set(seen)) == len(LINES)


@pytest.mark.unit
def test_no_split_can_be_won_by_one_constant_label() -> None:
    for split in (TRAIN, VALIDATION, HELD_OUT):
        for label in LABELS:
            labelled = [line for line in split if line.label == label]
            assert labelled, f"{label} is missing from a split"
            assert len(labelled) < len(split)


@pytest.mark.unit
def test_every_line_carries_a_reason_the_evaluator_can_return() -> None:
    assert all(line.reason.strip() for line in LINES)
