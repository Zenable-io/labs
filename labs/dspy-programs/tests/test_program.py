"""Copyright (c) 2026 Zenable, Inc. Unit tests for the parts of the lab that do not need the model running."""

import collections

import dspy
from dspylab import program as lab
from dspylab.commits import COMMITS, DEVELOPMENT, HELD_OUT, TRAIN, TYPES


def prediction(commit_type: str | None) -> dspy.Prediction:
    return dspy.Prediction(commit_type=commit_type)


def test_every_commit_lands_in_exactly_one_split() -> None:
    splits = [TRAIN, DEVELOPMENT, HELD_OUT]
    assert sum(len(split) for split in splits) == len(COMMITS)
    subjects = [commit.subject for split in splits for commit in split]
    assert len(set(subjects)) == len(COMMITS)


def test_every_type_appears_in_every_split() -> None:
    for split in (TRAIN, DEVELOPMENT, HELD_OUT):
        assert {commit.commit_type for commit in split} == set(TYPES)


def test_the_vocabulary_is_written_once() -> None:
    field = lab.ClassifyCommit.output_fields["commit_type"]
    assert set(getattr(field.annotation, "__args__", ())) == set(TYPES)


def test_the_metric_is_exact_match() -> None:
    gold = lab.examples(COMMITS[:1])[0]
    assert lab.metric(gold, prediction(gold.commit_type)) == 1.0
    assert lab.metric(gold, prediction("chore")) == 0.0
    assert lab.metric(gold, prediction(None)) == 0.0


def test_examples_declare_the_subject_as_the_only_input() -> None:
    example = lab.examples(COMMITS[:1])[0]
    assert set(example.inputs().keys()) == {"subject"}
    assert example.commit_type == COMMITS[0].commit_type


def test_confusion_counts_right_over_total_per_type() -> None:
    examples = lab.examples(TRAIN)
    results = [
        (example, prediction(example.commit_type), 1.0) for example in examples[:4]
    ]
    results += [(example, prediction("chore"), 0.0) for example in examples[4:6]]
    counts = lab.confusion(results)
    totals = collections.Counter(example.commit_type for example, _, _ in results)
    for commit_type, (right, total) in counts.items():
        assert total == totals[commit_type]
        assert right <= total


def test_mistakes_report_what_was_answered_instead() -> None:
    example = lab.examples(TRAIN)[0]
    wrong_type = next(name for name in TYPES if name != example.commit_type)
    ((subject, expected, answered),) = lab.mistakes(
        [(example, prediction(wrong_type), 0.0)]
    )
    assert subject == example.subject
    assert expected == example.commit_type
    assert answered == wrong_type


def test_asking_for_reasoning_adds_a_field_the_signature_never_declared() -> None:
    plain = lab.build(reasoning=False)
    reasoning = lab.build(reasoning=True)
    assert plain.signature is lab.ClassifyCommit
    assert set(plain.signature.output_fields) == {"commit_type"}
    # ChainOfThought wraps the same signature and puts `reasoning` in front of
    # the answer, so the model writes its way to the type rather than naming it
    # first. Same fields in, one more field out, no prompt written by hand.
    assert list(reasoning.predict.signature.output_fields) == [
        "reasoning",
        "commit_type",
    ]
