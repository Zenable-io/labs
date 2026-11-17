"""Copyright (c) 2026 Zenable, Inc. The DSPy program, the metric it is scored by, and the model underneath it.

The program is three lines: a signature naming what goes in and what comes out,
a module that decides how to ask, and a metric that decides whether the answer
was right. Nothing in this file writes a prompt. DSPy builds the prompt from
the signature, and an optimiser rewrites the parts of it that are data --
which examples to show, and eventually the instruction itself.

The model is a 0.5B instruct model on the machine you are sitting at. It reads
English well enough to guess, and knows nothing about which convention this
repository follows, so the demos an optimiser picks are the whole difference
between a bad score and a good one.
"""

import collections
import os
from typing import Any

import dspy

from dspylab.commits import COMMITS, Commit, CommitType

DEFAULT_MODEL = "qwen2.5:0.5b-instruct"
DEFAULT_API_BASE = "http://127.0.0.1:11434"


class ClassifyCommit(dspy.Signature):
    """Give the Conventional Commits type of a git commit subject line."""

    subject: str = dspy.InputField(desc="the subject line of one commit")
    commit_type: CommitType = dspy.OutputField(desc="the type this commit belongs to")


def configure(model: str = DEFAULT_MODEL, api_base: str | None = None) -> dspy.LM:
    """Point DSPy at the local model and return the handle for `inspect_history`."""
    lm = dspy.LM(
        f"ollama_chat/{model}",
        # OLLAMA_API_BASE names the server, as LiteLLM reads it; DSPy's own
        # `ollama_chat` client needs the OpenAI-compatible API under /v1.
        api_base=f"{(api_base or os.environ.get('OLLAMA_API_BASE', DEFAULT_API_BASE)).rstrip('/')}/v1",
        api_key="unused",
        temperature=0.0,
        max_tokens=200,
        # Caching would make the second evaluation of an unchanged program free
        # and instant, which reads as a speed-up that is really a cache hit.
        cache=False,
    )
    dspy.configure(lm=lm)
    return lm


def build(reasoning: bool = False) -> dspy.Module:
    """`Predict` asks for the answer; `ChainOfThought` asks for the reasoning too."""
    if reasoning:
        return dspy.ChainOfThought(ClassifyCommit)
    return dspy.Predict(ClassifyCommit)


def examples(commits: tuple[Commit, ...]) -> list[dspy.Example]:
    return [
        dspy.Example(
            subject=commit.subject, commit_type=commit.commit_type
        ).with_inputs("subject")
        for commit in commits
    ]


def metric(gold: dspy.Example, prediction: Any, trace: Any = None) -> float:
    """Exact match on the type. One number, because an optimiser needs one."""
    return float(getattr(prediction, "commit_type", None) == gold.commit_type)


def confusion(results: list[tuple[dspy.Example, Any, float]]) -> dict[str, list[int]]:
    """Per-type (right, total), so a score can be read as more than an average."""
    counts: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for gold, _prediction, score in results:
        counts[gold.commit_type][1] += 1
        counts[gold.commit_type][0] += int(score >= 1.0)
    return dict(counts)


def mistakes(
    results: list[tuple[dspy.Example, Any, float]],
) -> list[tuple[str, str, str]]:
    """(subject, expected, answered) for every example the program got wrong."""
    wrong = []
    for gold, prediction, score in results:
        if score >= 1.0:
            continue
        answered = str(getattr(prediction, "commit_type", "(nothing)"))
        wrong.append((gold.subject, gold.commit_type, answered))
    return wrong


ALL = examples(COMMITS)
