# Copyright (c) 2026 Zenable, Inc.

"""Reflection models GEPA calls, live or replayed, and its iteration events."""

from pathlib import Path
from typing import Any

import litellm
from pydantic import BaseModel, Field

# One terminal line per example, so a pause stays readable.
FEEDBACK_CHARS = 100


class LiveReflection(BaseModel):
    """Ask the model for a new prompt, and keep every reply so a run can be recorded."""

    model: str
    kwargs: dict[str, Any] = Field(default_factory=dict)
    replies: list[str] = Field(default_factory=list)

    def __call__(self, prompt: str) -> str:
        response = litellm.completion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            timeout=120,
            **self.kwargs,
        )
        reply = response.choices[0].message.content or ""
        self.replies.append(reply)
        return reply


class RecordedReflection(BaseModel):
    """Hand back a real run's replies in the order it got them."""

    replies: tuple[str, ...] = Field(min_length=1)
    calls: int = 0

    def __call__(self, prompt: str) -> str:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply


class StepObserver(BaseModel):
    log_path: Path
    pause: bool
    refinements: int
    verbose: bool = False
    stopped: bool = False

    def log(self, message: str) -> None:
        with self.log_path.open("a") as output:
            output.write(message + "\n")
        if self.verbose:
            print(message)

    def __call__(self, state: object) -> bool:
        return self.stopped

    def on_candidate_selected(self, event: dict[str, Any]) -> None:
        print(
            f"\nRefinement {event['iteration']}: select candidate {event['candidate_idx']}"
        )
        print(f"  validation: {event['score']:.1%}")

    def on_minibatch_sampled(self, event: dict[str, Any]) -> None:
        print(f"  collect feedback on {len(event['minibatch_ids'])} training examples")

    def on_reflective_dataset_built(self, event: dict[str, Any]) -> None:
        print("  feedback the reflection model reads:")
        for rows in event["dataset"].values():
            for row in rows:
                text = row["feedback"]
                if len(text) > FEEDBACK_CHARS:
                    text = text[: FEEDBACK_CHARS - 1] + "…"
                print(f"    - {text}")

    def on_proposal_end(self, event: dict[str, Any]) -> None:
        print("  proposed prompt:")
        for text in event["new_instructions"].values():
            for line in text.splitlines():
                print(f"    {line}")

    def on_candidate_rejected(self, event: dict[str, Any]) -> None:
        print("  minibatch did not improve; discard this proposal")

    def on_valset_evaluated(self, event: dict[str, Any]) -> None:
        print(
            f"  validation: {event['average_score']:.1%} on {event['num_examples_evaluated']} examples"
        )

    def on_iteration_end(self, event: dict[str, Any]) -> None:
        if self.pause and event["iteration"] < self.refinements:
            try:
                self.stopped = (
                    input("Enter for the next refinement, or q to finish: ")
                    .strip()
                    .lower()
                    == "q"
                )
            except EOFError:
                self.stopped = True
