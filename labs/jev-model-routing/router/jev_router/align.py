"""Copyright (c) 2026 Zenable, Inc. Grade the routing policy against the labels a person wrote, and adopt a better one.

`measure.py` grades a cache against Jev. Nothing there asks whether Jev agrees
with anybody, because a cache can be perfect about an answer that is wrong.
This module asks that question instead: every family in the corpus carries a
`kind` decided by hand before any Jev call, and `grade` scores the routing
answers against those labels.

`export` writes the same corpus out as a CSV for `jeva`, the jev-align CLI,
which offers you the requests Jev is least sure about, takes your label for
each, and runs GEPA over the accumulated labels to propose new criteria.
`adopt` takes the definition you accepted there and writes it into
`policy.json`, which is the file the router reads.
"""

import argparse
import asyncio
import collections
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, ValidationError

from jev_router.catalog import (
    CATALOG,
    MODEL_NAMES,
    POLICY_FILE,
    RoutingPolicy,
    load_policy,
)
from jev_router.config import RouterSettings
from jev_router.corpus import FAMILIES, FAMILY_OF, MESSAGES
from jev_router.house import HOUSE_FAMILY_OF, HOUSE_MESSAGES, HOUSE_RULE
from jev_router.measure import build_oracle

KIND_TO_MODEL: dict[str, str] = {
    "mechanical": CATALOG[0].name,
    "deliberative": CATALOG[-1].name,
}
"""What the hand-written label means in terms of the catalogue.

The corpus labels the work, not the model, so this mapping is the claim that
the cheap model is the right home for mechanical work. It holds for a two-model
catalogue ordered by cost; a third model would need labels of its own rather
than another entry here."""

LARGEST_MODEL = CATALOG[-1].name


MIXED_ORDINARY = 16
"""How many of the original requests ride along with the money-touching ones.

A pool where every answer is the same teaches an optimiser the answer rather
than the rule: labelling twenty-four money requests `qwen-large` and nothing
else is indistinguishable from labelling everything `qwen-large`. These carry
the other side of the boundary, so the criteria that come back have to place it
rather than erase it."""


def _ordinary_sample(count: int = MIXED_ORDINARY) -> tuple[str, ...]:
    """The first form of every other family, cheap side and expensive side alike.

    Taken by stride rather than at random so two exports of the same rig hand
    the same requests to the same person twice.
    """
    firsts = [family.forms[0] for family in FAMILIES]
    mechanical = [form for form in firsts if FAMILY_OF[form].kind == "mechanical"]
    deliberative = [form for form in firsts if FAMILY_OF[form].kind == "deliberative"]
    half = count // 2
    return tuple(mechanical[:half] + deliberative[: count - half])


def _corpus_labels(name: str) -> tuple[tuple[str, ...], dict[str, tuple[str, str]]]:
    """Messages, and `message -> (family name, the model it should reach)`.

    The corpora are labelled by different people for different reasons. The
    original carries the kind of work, which the criteria were written from. The
    house one carries a rule the criteria have never been told. `mixed` is what
    you hand a labeller, because a boundary needs both sides of it.
    """
    house = {
        message: (family.name, LARGEST_MODEL)
        for message, family in HOUSE_FAMILY_OF.items()
    }
    ordinary = {
        message: (family.name, KIND_TO_MODEL[family.kind])
        for message, family in FAMILY_OF.items()
    }
    if name == "house":
        return HOUSE_MESSAGES, house
    if name == "mixed":
        sample = _ordinary_sample()
        return HOUSE_MESSAGES + sample, {
            **{message: ordinary[message] for message in sample},
            **house,
        }
    return MESSAGES, ordinary


def _group_of(name: str, message: str) -> str:
    """How `grade` breaks the table up.

    The house corpus splits on how the criteria read a request, because that is
    where it disagrees with the rule. The mixed pool splits on which side of the
    boundary a request sits, because that is the thing being taught.
    """
    if name == "house":
        return HOUSE_FAMILY_OF[message].reads_as
    if name == "mixed":
        if message in HOUSE_FAMILY_OF:
            return f"money, reads as {HOUSE_FAMILY_OF[message].reads_as}"
        return f"ordinary {FAMILY_OF[message].kind}"
    return FAMILY_OF[message].kind


class Disagreement(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    message: str
    family: str
    expected: str
    answered: str
    confidence: float


class Grade(BaseModel):
    """How well one set of answers matches the labels."""

    model_config = ConfigDict(frozen=True, strict=True)

    policy: str
    graded: int
    agreed: int
    by_kind: dict[str, tuple[int, int]]
    """kind -> (agreed, graded)."""

    disagreements: tuple[Disagreement, ...]

    @property
    def accuracy(self) -> float:
        return self.agreed / self.graded if self.graded else 0.0


def grade(oracle: dict[str, Any], corpus: str = "corpus") -> Grade:
    """Score one oracle file against the labels a person wrote for that corpus."""
    answers = oracle.get("answers") or {}
    messages, labels = _corpus_labels(corpus)
    agreed = 0
    graded = 0
    by_kind: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    disagreements: list[Disagreement] = []

    for message in messages:
        answer = answers.get(message)
        if answer is None:
            continue
        family_name, expected = labels[message]
        group = _group_of(corpus, message)
        answered = str(answer.get("model", ""))
        graded += 1
        by_kind[group][1] += 1
        if answered == expected:
            agreed += 1
            by_kind[group][0] += 1
            continue
        disagreements.append(
            Disagreement(
                message=message,
                family=family_name,
                expected=expected,
                answered=answered,
                confidence=float(answer.get("confidence", 0.0)),
            )
        )

    return Grade(
        policy=str(oracle.get("policy", "unknown")),
        graded=graded,
        agreed=agreed,
        by_kind={kind: (counts[0], counts[1]) for kind, counts in by_kind.items()},
        disagreements=tuple(disagreements),
    )


def load_oracle(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Run `python -m jev_router.measure oracle` to "
            "write one, or copy the recorded file this rig ships."
        )
    return json.loads(path.read_text())


def spec_from_state(state: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """The instructions and criteria a jev-align run currently stands behind."""
    if state.get("pending_candidate"):
        raise SystemExit(
            "that run has a proposal you have not accepted or rejected yet. "
            "Finish it with `jeva optimize --resume <run>` first."
        )
    candidate = state.get("current_candidate") or {}
    instructions = str(candidate.get("instructions", "")).strip()
    criteria = candidate.get("criteria")
    if not instructions or not isinstance(criteria, dict):
        raise SystemExit(
            "that run is not a multiclass task over the routing criteria, so there "
            "is nothing here to adopt."
        )
    return instructions, {str(name): str(text) for name, text in criteria.items()}


def policy_from_spec(instructions: str, criteria: dict[str, str]) -> RoutingPolicy:
    missing = MODEL_NAMES - set(criteria)
    unknown = set(criteria) - MODEL_NAMES
    if missing or unknown:
        raise SystemExit(
            "the labels in that run do not match the catalogue. "
            f"missing {sorted(missing)}, unexpected {sorted(unknown)}. "
            "The class names have to be the model names the gateway defines."
        )
    # Ordered by the catalogue rather than by the run, because the first entry
    # is where an undecided request goes.
    return RoutingPolicy(
        question=instructions,
        focus="",
        models=tuple(
            model.model_copy(update={"criterion": criteria[model.name]})
            for model in CATALOG
        ),
    )


def cmd_oracle(args: argparse.Namespace) -> int:
    """Ask Jev about every message in one corpus, once, and write the answers."""
    messages, _ = _corpus_labels(args.corpus)
    settings = RouterSettings.from_env()
    oracle = asyncio.run(build_oracle(settings, messages))
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
    print(
        f"asked Jev about {len(oracle['answers'])} messages in the {args.corpus} corpus"
    )
    print(f"wrote {args.out} under policy {oracle['policy']}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    """Write the `jeva` command that starts from the policy this router runs.

    The criteria are read out of `policy.json` rather than typed again here, so
    the search starts from the definition in use and every proposal it makes is
    a move away from that rather than from something close to it.
    """
    policy = load_policy()
    parts = [
        "jeva optimize",
        f"  {args.data}",
        "  --column message",
        f"  --question {_quote(policy.question)}",
    ]
    parts.extend(
        f"  --class {_quote(f'{model.name}={model.criterion}')}"
        for model in policy.models
    )
    parts.extend(
        [
            # jeva's own default names a pinned Jev release that OpenRouter does
            # not serve, so the search asks the model the router asks.
            f"  --jev-model {_quote(args.jev_model)}",
            f"  --batch-size {args.batch_size}",
            f"  --concurrency {args.concurrency}",
            f"  --max-metric-calls {args.max_metric_calls}",
        ]
    )
    reflection_model = args.reflection_model or _sandbox_reflection_model()
    if reflection_model:
        parts.append(f"  --reflection-model {_quote(reflection_model)}")

    script = " \\\n".join(parts) + "\n"
    Path(args.out).write_text(script)
    print(f"wrote {args.out}, which runs:\n")
    print(script)
    print("run it with `sh " + args.out + "`; it asks you for every label.")
    return 0


def _sandbox_reflection_model() -> str | None:
    """The model a Zenable sandbox's OpenRouter key is for, as LiteLLM names it.

    That key also fills OPENAI_API_KEY pointed at OpenRouter, which jeva's own
    detection would read as an OpenAI key, so the seed names the model instead.
    """
    load_dotenv(Path.home() / ".env", override=True)
    sandbox_model = os.environ.get("ZENABLE_SANDBOX_MODEL")
    if os.environ.get("OPENROUTER_API_KEY") and sandbox_model:
        return f"openrouter/{sandbox_model}"
    return None


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def cmd_export(args: argparse.Namespace) -> int:
    messages, _ = _corpus_labels(args.corpus)
    path = Path(args.out)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["message"])
        writer.writerows([message] for message in messages)
    print(f"wrote {path} with {len(messages)} requests")
    print("the labels stay here: jev-align asks you for every one of them")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    result = grade(load_oracle(Path(args.oracle)), args.corpus)
    if args.corpus == "house":
        print(f"house rule: {HOUSE_RULE}")
    print(f"policy {result.policy}, {result.graded} messages graded by hand\n")
    heading = "reads as" if args.corpus == "house" else "kind"
    # Widened to whatever the longest group name is: the mixed pool names both
    # sides of the boundary, and those names are longer than a column written
    # for "mechanical".
    width = max(len(heading), 7, *(len(name) for name in result.by_kind)) + 2
    print(f"{heading:<{width}}{'agrees':>8}{'of':>5}{'':>3}{'rate':>7}")
    for kind, (agreed, graded) in sorted(result.by_kind.items()):
        rate = agreed / graded if graded else 0.0
        print(f"{kind:<{width}}{agreed:>8}{graded:>5}{'':>3}{rate:>6.1%}")
    print(
        f"{'overall':<{width}}{result.agreed:>8}{result.graded:>5}"
        f"{'':>3}{result.accuracy:>6.1%}"
    )

    if not result.disagreements:
        print("\nevery request went where the label says it should")
        return 0

    shown = result.disagreements[: args.show]
    print(f"\n{len(result.disagreements)} disagreements, the first {len(shown)}:")
    for item in shown:
        print(
            f"  {item.family:<20} label {item.expected:<11} jev {item.answered} ({item.confidence:.2f})"
        )
        print(f"    {item.message[:100]}")
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    state_path = Path(args.run) / "state.json"
    if not state_path.exists():
        raise SystemExit(
            f"{state_path} does not exist, so that is not a jev-align run."
        )
    try:
        instructions, criteria = spec_from_state(json.loads(state_path.read_text()))
        policy = policy_from_spec(instructions, criteria)
    except ValidationError as error:
        raise SystemExit(
            f"that run does not describe a routing policy: {error}"
        ) from error

    before = load_policy()
    if args.dry_run:
        print(json.dumps(policy.model_dump(), indent=2))
        return 0

    POLICY_FILE.write_text(json.dumps(policy.model_dump(), indent=2) + "\n")
    print(f"wrote {POLICY_FILE}")
    # Both fingerprints are computed from the policies in hand. `catalog` read
    # its copy at import, so asking it would answer for the file as it was when
    # this process started, which is the one being replaced.
    print(
        f"policy {_fingerprint_of(policy, args.jev_model)}, "
        f"was {_fingerprint_of(before, args.jev_model)}"
    )
    print(
        "every cache entry and every recorded decision under the old policy is now unreachable"
    )
    return 0


def _fingerprint_of(policy: RoutingPolicy, jev_model: str) -> str:
    """The fingerprint a policy would produce, without installing it."""
    instructions: dict[str, str] = {"question": policy.question}
    if policy.focus:
        instructions["focus"] = policy.focus
    payload = json.dumps(
        {
            "jev_model": jev_model,
            "questions": {
                "route": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": {
                        model.name: model.criterion for model in policy.models
                    },
                }
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jev_router.align", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    oracle = commands.add_parser("oracle", help="ask Jev about one corpus, once")
    oracle.add_argument(
        "--corpus", choices=("corpus", "house", "mixed"), default="house"
    )
    oracle.add_argument("--out", default="house-oracle.json")
    oracle.set_defaults(handler=cmd_oracle)

    seed = commands.add_parser(
        "seed", help="write the jev-align command for this policy"
    )
    seed.add_argument("--data", default="house.csv")
    seed.add_argument("--out", default="jeva-run.sh")
    seed.add_argument("--batch-size", type=int, default=10)
    seed.add_argument("--concurrency", type=int, default=6)
    seed.add_argument("--max-metric-calls", type=int, default=120)
    seed.add_argument("--reflection-model", help="LiteLLM model name for GEPA")
    seed.add_argument(
        "--jev-model",
        default=RouterSettings.model_fields["jev_model"].default,
        help="the Jev model the search evaluates with; the router's by default",
    )
    seed.set_defaults(handler=cmd_seed)

    export = commands.add_parser("export", help="write a corpus out for jev-align")
    export.add_argument(
        "--corpus", choices=("corpus", "house", "mixed"), default="house"
    )
    export.add_argument("--out", default="house.csv")
    export.set_defaults(handler=cmd_export)

    grading = commands.add_parser(
        "grade", help="score an oracle against the hand labels"
    )
    grading.add_argument(
        "--corpus", choices=("corpus", "house", "mixed"), default="house"
    )
    grading.add_argument("--oracle", default="house-oracle.json")
    grading.add_argument("--show", type=int, default=6)
    grading.set_defaults(handler=cmd_grade)

    adopt = commands.add_parser(
        "adopt", help="install the definition you accepted in jev-align"
    )
    adopt.add_argument("run", help="a .jev-align/runs/<run-id> directory")
    adopt.add_argument(
        "--jev-model", default=RouterSettings.model_fields["jev_model"].default
    )
    adopt.add_argument(
        "--dry-run", action="store_true", help="print it instead of writing it"
    )
    adopt.set_defaults(handler=cmd_adopt)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
