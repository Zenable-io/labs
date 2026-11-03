"""Copyright (c) 2026 Zenable, Inc. The four exercises, as one command each.

Every command takes `--fixtures`, which replays answers recorded from a real run
instead of calling Jev. That is the path this rig's tests take, and the path for
anyone without a key.
"""

import argparse
import json
import sys
from typing import Any

from jevlab import subjects
from jevlab.client import FIXTURE_FILE, FixtureMiss, JevClient, Recording, fingerprint
from jevlab.levels import rubric_score
from jevlab.questions import (
    engine_choice_questions,
    engine_noul_questions,
    rank_questions,
    rubric_questions,
)

FOCUS_REQUIREMENT = "money-as-minor-units"
SMOKE_QUESTIONS: dict[str, Any] = {
    "is_python": {
        "type": "noul",
        "instructions": {"question": "Is `file.content` Python source?"},
    },
    "changes_an_amount": {
        "type": "noul",
        "instructions": {
            "question": (
                "Do the changed lines in `file.patch` change how an amount of "
                "money is calculated?"
            )
        },
    },
}


def _pass_name(base: str, index: int) -> str:
    return f"{base}#{index}"


def _rank_state() -> dict[str, object]:
    return {
        "file": subjects.file_state(),
        "requirements": {
            requirement.name: requirement.model_dump()
            for requirement in subjects.REQUIREMENTS
        },
    }


def _engine_state() -> dict[str, object]:
    return {
        "requirement": next(
            requirement.model_dump()
            for requirement in subjects.REQUIREMENTS
            if requirement.name == FOCUS_REQUIREMENT
        ),
        "engines": {engine.name: engine.model_dump() for engine in subjects.ENGINES},
    }


def _rubric_state() -> dict[str, object]:
    return {"candidate": {"statement": subjects.CANDIDATE_REQUIREMENT}}


def cmd_ask(client: JevClient) -> int:
    answers = client.ask("ask#1", {"file": subjects.file_state()}, SMOKE_QUESTIONS)
    print(json.dumps(answers, indent=2, sort_keys=True))
    return 0


def _rank_pass(
    client: JevClient, anchor: str, index: int
) -> list[tuple[str, float, float]]:
    answers = client.ask(
        _pass_name(f"rank:{anchor}", index), _rank_state(), rank_questions(anchor)
    )
    rows = [
        (
            requirement.name,
            float(answers[f"governs::{requirement.name}"]["noul"]),
            float(answers[f"breaks::{requirement.name}"]["noul"]),
        )
        for requirement in subjects.REQUIREMENTS
    ]
    rows.sort(key=lambda row: row[1], reverse=True)
    return rows


def cmd_rank(client: JevClient, anchor: str, top: int, repeat: int) -> int:
    passes = [_rank_pass(client, anchor, index) for index in range(1, repeat + 1)]

    if repeat == 1:
        rows = passes[0]
        print(f"anchor: {anchor}")
        print(f"{'rank':>4}  {'requirement':<28}{'governs':>9}{'breaks':>8}")
        for rank, (name, governs, breaks) in enumerate(rows, start=1):
            marker = "*" if rank <= top else " "
            print(f"{rank:>4}{marker} {name:<28}{governs:>9.2f}{breaks:>8.2f}")
        over_floor = sum(1 for _, governs, _ in rows if governs >= 0.5)
        print(f"\ntop {top} by rank: {', '.join(name for name, _, _ in rows[:top])}")
        print(f"a 0.50 floor on `governs` would have kept {over_floor} of {len(rows)}")
        return 0

    for index, rows in enumerate(passes, start=1):
        print(f"pass {index}: {' > '.join(name for name, _, _ in rows[:top])}")
    orders = {tuple(name for name, _, _ in rows[:top]) for rows in passes}
    memberships = {tuple(sorted(entry)) for entry in orders}
    print(
        f"\ntop {top} set identical on all {repeat} passes:   {len(memberships) == 1}"
    )
    print(f"top {top} order identical on all {repeat} passes: {len(orders) == 1}")
    print(f"\n{'requirement':<28}{'governs range':>16}{'spread':>9}")
    spans = [
        (
            requirement.name,
            [
                next(governs for name, governs, _ in rows if name == requirement.name)
                for rows in passes
            ],
        )
        for requirement in subjects.REQUIREMENTS
    ]
    for name, values in sorted(spans, key=lambda span: max(span[1]), reverse=True):
        print(
            f"{name:<28}{min(values):>9.2f}-{max(values):<6.2f}{max(values) - min(values):>9.2f}"
        )
    return 0


def cmd_engines(client: JevClient, shape: str) -> int:
    state = _engine_state()
    if shape == "noul":
        answers = client.ask(
            _pass_name("engines:noul", 1),
            state,
            engine_noul_questions(FOCUS_REQUIREMENT),
        )
        print(f"requirement: {FOCUS_REQUIREMENT}   shape: one Noul per engine\n")
        print(f"{'engine':<12}{'p(can check)':>13}")
        kept = 0
        for engine in subjects.ENGINES:
            probability = float(answers[engine.name]["noul"])
            kept += probability >= 0.30
            print(f"{engine.name:<12}{probability:>13.2f}")
        print(f"\na 0.30 floor keeps {kept} of {len(subjects.ENGINES)} engines")
        print("one number per engine, so nothing here says which of them need help")
        return 0

    answers = client.ask(
        _pass_name("engines:choice", 1),
        state,
        engine_choice_questions(FOCUS_REQUIREMENT),
    )
    print(f"requirement: {FOCUS_REQUIREMENT}   shape: one Choice per engine\n")
    print(
        f"{'engine':<12}{'choice':>9}{'full':>7}{'partial':>9}{'none':>7}  include  guidance"
    )
    for engine in subjects.ENGINES:
        answer = answers[engine.name]
        probabilities = {
            str(key): float(value) for key, value in answer["probabilities"].items()
        }
        full = probabilities.get("full", 0.0)
        partial = probabilities.get("partial", 0.0)
        none = probabilities.get("none", 0.0)
        include = "yes" if full + partial >= 0.30 else "no"
        guidance = "yes" if include == "yes" and partial > full else "no"
        print(
            f"{engine.name:<12}{answer['choice']:>9}{full:>7.2f}{partial:>9.2f}{none:>7.2f}"
            f"{include:>9}{guidance:>10}"
        )
    print(
        "\ninclude when p(full) + p(partial) >= 0.30; guidance when p(partial) > p(full)"
    )
    return 0


def cmd_grade(client: JevClient, reading: str) -> int:
    answers = client.ask(
        _pass_name(f"grade:{reading}", 1), _rubric_state(), rubric_questions(reading)
    )
    print(f"reading: {reading}\n")
    print(f"{'dimension':<14}{'position':>9}{'score 0-10':>12}   distribution")
    total = 0.0
    for name in ("testability", "specificity", "scope"):
        answer = answers[name]
        probabilities = {
            int(key): float(value) for key, value in answer["probabilities"].items()
        }
        score = rubric_score(probabilities)
        total += score
        spread = " ".join(
            f"{level}:{probabilities.get(level, 0.0):.2f}"
            for level in sorted(probabilities)
        )
        print(f"{name:<14}{answer['score']:>9.2f}{score:>12.2f}   {spread}")
    print(f"\nmean of the three 0-10 scores: {total / 3:.2f}")
    print("`position` is where the answer sits on the level number line, 0 to 4")
    print("`score 0-10` re-weights the same distribution over the anchors")
    return 0


def cmd_record(client: JevClient) -> int:
    """Re-record every answer the exercises replay. Needs a key."""
    plan: list[tuple[str, Any, dict[str, Any]]] = [
        ("ask#1", {"file": subjects.file_state()}, SMOKE_QUESTIONS),
        (
            "engines:choice#1",
            _engine_state(),
            engine_choice_questions(FOCUS_REQUIREMENT),
        ),
        ("engines:noul#1", _engine_state(), engine_noul_questions(FOCUS_REQUIREMENT)),
        ("grade:quality#1", _rubric_state(), rubric_questions("quality")),
        ("grade:risk#1", _rubric_state(), rubric_questions("risk")),
    ]
    for anchor in ("patch", "file"):
        for index in (1, 2, 3):
            plan.append(
                (
                    _pass_name(f"rank:{anchor}", index),
                    _rank_state(),
                    rank_questions(anchor),
                )
            )

    recordings = []
    for scenario, state, questions in plan:
        answers = client.ask(scenario, state, questions)
        recordings.append(
            Recording(
                scenario=scenario,
                fingerprint=fingerprint(questions),
                model=client.model,
                answers=answers,
            ).model_dump()
        )
        print(f"recorded {scenario}")
    FIXTURE_FILE.write_text(json.dumps(recordings, indent=2, sort_keys=True) + "\n")
    print(
        f"\nwrote {len(recordings)} recordings to {FIXTURE_FILE.relative_to(FIXTURE_FILE.parents[2])}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jevlab", description=__doc__)
    # Every command takes it, and it reads better at the end of the line than
    # in front of the command it applies to.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--fixtures", action="store_true", help="replay recorded answers"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "ask", parents=[common], help="two Nouls against the changed file"
    )

    rank = commands.add_parser(
        "rank", parents=[common], help="two Nouls per requirement, ranked"
    )
    rank.add_argument("--anchor", choices=("patch", "file"), default="patch")
    rank.add_argument("--top", type=int, default=3)
    rank.add_argument("--repeat", type=int, default=1)

    engines = commands.add_parser(
        "engines", parents=[common], help="which engines can check a requirement"
    )
    engines.add_argument("--shape", choices=("choice", "noul"), default="choice")

    grade = commands.add_parser(
        "grade", parents=[common], help="score a proposed requirement"
    )
    grade.add_argument("--reading", choices=("quality", "risk"), default="quality")

    commands.add_parser(
        "record", parents=[common], help="re-record the fixtures (needs a key)"
    )

    args = parser.parse_args(argv)
    client = JevClient(fixtures=args.fixtures)
    try:
        if args.command == "ask":
            return cmd_ask(client)
        if args.command == "rank":
            return cmd_rank(client, args.anchor, args.top, args.repeat)
        if args.command == "engines":
            return cmd_engines(client, args.shape)
        if args.command == "grade":
            return cmd_grade(client, args.reading)
        return cmd_record(client)
    except FixtureMiss as miss:
        print(f"fixture miss: {miss}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
