"""Copyright (c) 2026 Zenable, Inc. The commands this lab runs.

Everything but `jev` talks to the model on this machine and nothing else. The
`jev` commands ask TypeSafe's System One API, with the key in ~/.env, or replay
a real run's answers with `--fixtures`.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import dspy
from dotenv import load_dotenv
from dspy.experimental import ReAnchor, TypeSafe

from dspylab import jev
from dspylab import program as lab
from dspylab.commits import DEVELOPMENT, HELD_OUT, TRAIN

SPLITS = {"train": TRAIN, "development": DEVELOPMENT, "held-out": HELD_OUT}

COMPILED_DEFAULT = Path("compiled.json")
JEV_COMPILED_DEFAULT = Path("jev-compiled.json")


def _load_program(path: Path | None, reasoning: bool) -> dspy.Module:
    module = lab.build(reasoning=reasoning)
    if path is None:
        return module
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Run `python -m dspylab compile` to make one."
        )
    module.load(str(path))
    return module


def _evaluate(module: dspy.Module, split: str, threads: int) -> tuple[float, list[Any]]:
    examples = lab.examples(SPLITS[split])
    runner = dspy.Evaluate(
        devset=examples,
        metric=lab.metric,
        num_threads=threads,
        display_progress=False,
        failure_score=0.0,
    )
    outcome = runner(module)
    return float(outcome.score), list(outcome.results)


def _print_results(split: str, score: float, results: list[Any], show: int) -> None:
    print(f"\n{split}: {score:.1f}% exact match over {len(results)} lines\n")
    print(f"{'type':<12}{'right':>7}{'of':>5}")
    for commit_type, (right, total) in sorted(lab.confusion(results).items()):
        print(f"{commit_type:<12}{right:>7}{total:>5}")
    wrong = lab.mistakes(results)
    if not wrong:
        print("\nevery line is typed correctly")
        return
    print(f"\n{len(wrong)} wrong, the first {min(show, len(wrong))}:")
    for subject, expected, answered in wrong[:show]:
        print(f"  {expected:<9} answered {answered:<9} {subject}")


def cmd_evaluate(args: argparse.Namespace) -> int:
    lab.configure(args.model)
    module = _load_program(Path(args.program) if args.program else None, args.reasoning)
    score, results = _evaluate(module, args.split, args.threads)
    _print_results(args.split, score, results, args.show)
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    lab.configure(args.model)
    student = lab.build(reasoning=args.reasoning)

    before, _ = _evaluate(student, "development", args.threads)
    print(f"\nbefore compiling: {before:.1f}% on development\n")

    # `BootstrapFewShot` runs the program over the training set, keeps the
    # attempts the metric scored as correct, and installs them as demonstrations.
    # A wrong answer is never kept, so a demo is an example of this model
    # succeeding rather than an example a person wrote.
    optimiser = dspy.BootstrapFewShot(
        metric=lab.metric,
        max_bootstrapped_demos=args.demos,
        max_labeled_demos=args.labeled,
        max_rounds=1,
    )
    compiled = optimiser.compile(student, trainset=lab.examples(TRAIN))

    after, results = _evaluate(compiled, "development", args.threads)
    print(f"\nafter compiling:  {after:.1f}% on development")
    print(f"change:           {after - before:+.1f} points\n")
    _print_results("development", after, results, args.show)

    out = Path(args.out)
    compiled.save(str(out))
    print(f"\nsaved {out}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    path = Path(args.program)
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Run `python -m dspylab compile` to make one."
        )
    saved = json.loads(path.read_text())
    # A program with one predictor saves that predictor's own keys at the top
    # level; a program with several saves one entry per predictor. This lab has
    # one, and reads either shape so a reader who adds a second module here does
    # not find this command quietly printing nothing.
    predictor = saved if "demos" in saved else next(iter(saved.values()), {})
    demos = predictor.get("demos", [])
    instructions = predictor.get("signature", {}).get("instructions")
    print(f"{path}: {len(demos)} demonstrations\n")
    if instructions:
        print(f"instruction:\n  {instructions}\n")
    for index, demo in enumerate(demos, start=1):
        subject = demo.get("subject", "")
        commit_type = demo.get("commit_type", "")
        source = "bootstrapped" if demo.get("augmented") else "labelled"
        print(f"{index:>2}. {commit_type:<9} {source:<13} {subject}")
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    lab.configure(args.model)
    module = _load_program(Path(args.program) if args.program else None, args.reasoning)
    prediction = module(subject=args.subject)
    print(f"answer: {prediction.commit_type}\n")
    print("the request DSPy built, in full:\n")
    # A file argument turns off the ANSI colours, so the terminal shows what
    # the lab's transcript quotes.
    dspy.inspect_history(n=1, file=sys.stdout)
    return 0


def _jev_program(path: str | None, weights: list[str]) -> dspy.Predict:
    parsed: dict[str, float] = {}
    for item in weights:
        commit_type, _, value = item.partition("=")
        if commit_type not in jev.TYPES or not value:
            raise SystemExit(
                f"--weight takes type=number, one of {', '.join(jev.TYPES)}; got {item!r}"
            )
        parsed[commit_type] = float(value)
    module = jev.build(parsed)
    if path is None:
        return module
    if not Path(path).exists():
        raise SystemExit(
            f"{path} does not exist. Run `python -m dspylab jev reanchor` to make one."
        )
    module.load(path)
    return module


def _jev_finish(lm: TypeSafe) -> int:
    live = jev.sent(lm)
    print(f"\n{live} answers from Jev, {len(lm.history) - live} from the cache")
    return 0


def _print_weights(weights: dict[str, float]) -> None:
    moved = {
        commit_type: value for commit_type, value in weights.items() if value != 1.0
    }
    if not moved:
        print("weights: every type at 1.0")
        return
    print(
        "weights: "
        + ", ".join(f"{commit_type} {value:g}" for commit_type, value in moved.items())
    )


def cmd_jev_ask(args: argparse.Namespace) -> int:
    lm = jev.configure(args.fixtures)
    module = _jev_program(args.program, args.weight)
    picked = module(subject=args.subject).commit_type
    print(f"answer: {picked}\n")
    weights = jev.weights_of(module)
    given = jev.probabilities(lm)
    ranked = sorted(
        given, key=lambda commit_type: -given[commit_type] * weights[commit_type]
    )
    if set(weights.values()) == {1.0}:
        print(f"{'type':<12}{'probability':>12}")
        for commit_type in ranked:
            print(f"{commit_type:<12}{given[commit_type]:>12.3f}")
    else:
        print(f"{'type':<12}{'probability':>12}{'weight':>8}{'weighted':>10}")
        for commit_type in ranked:
            weight = weights[commit_type]
            print(
                f"{commit_type:<12}{given[commit_type]:>12.3f}{weight:>8g}{given[commit_type] * weight:>10.3f}"
            )
    request = lm.history[-1]["request"]
    body = {
        "model": request["model"],
        "state": request["state"],
        "questions": request["questions"],
    }
    print(f"\nthe body DSPy posts to {request['base_url']}/v1/systemone:\n")
    print(json.dumps(body, indent=2))
    return _jev_finish(lm)


def cmd_jev_evaluate(args: argparse.Namespace) -> int:
    lm = jev.configure(args.fixtures)
    module = _jev_program(args.program, args.weight)
    _print_weights(jev.weights_of(module))
    score, results = _evaluate(module, args.split, args.threads)
    _print_results(args.split, score, results, args.show)
    return _jev_finish(lm)


def cmd_jev_reanchor(args: argparse.Namespace) -> int:
    lm = jev.configure(args.fixtures)
    # ReAnchor fits one weight per type against the metric, and keeps a weight
    # only if it also wins on folds of the training set it did not fit on.
    optimiser = ReAnchor(metric=lab.metric, num_threads=args.threads)
    compiled = optimiser.compile(
        jev.build(), trainset=lab.examples(TRAIN), valset=lab.examples(DEVELOPMENT)
    )
    report = optimiser.report
    # The report holds the metric's mean, 0 to 1; `evaluate` prints percent.
    print(
        f"\ntrain:       {report['train_score_before']:.1%} -> {report['train_score']:.1%}"
    )
    print(
        f"development: {report['val_score_before']:.1%} -> {report['val_score']:.1%}\n"
    )
    for row in report["fitted"]:
        if "skipped" in row:
            print(f"{row['field']}: left alone ({row['skipped']})")
            continue
        folds = row["fold_check"]
        print(
            f"{row['field']} {row['parameter']}, fold check {folds['passed']} passed / {folds['failed']} failed"
        )
    _print_weights(jev.weights_of(compiled))
    out = Path(args.out)
    compiled.save(str(out))
    print(f"\nsaved {out}")
    return _jev_finish(lm)


def cmd_jev_record(args: argparse.Namespace) -> int:
    """Re-record every answer the exercises replay. Needs a key.

    Label weights never reach the request, so one answer per line covers every
    command here, weighted or not, on any split.
    """
    lm = jev.configure(fixtures=False)
    module = jev.build()
    for commit in (*TRAIN, *DEVELOPMENT, *HELD_OUT):
        module(subject=commit.subject)
    saved = jev.recordings(lm)
    jev.FIXTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
    jev.FIXTURE_FILE.write_text(saved.model_dump_json(indent=2) + "\n")
    shown = jev.FIXTURE_FILE.relative_to(jev.FIXTURE_FILE.parents[2])
    print(f"wrote {len(saved.recordings)} recordings to {shown}")
    return _jev_finish(lm)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.home() / ".env", override=True)
    parser = argparse.ArgumentParser(prog="dspylab", description=__doc__)
    parser.add_argument("--model", default=lab.DEFAULT_MODEL, help="ollama model tag")
    commands = parser.add_subparsers(dest="command", required=True)

    evaluate = commands.add_parser("evaluate", help="score a program on one split")
    evaluate.add_argument("--split", choices=tuple(SPLITS), default="development")
    evaluate.add_argument("--program", help="a compiled.json to load first")
    evaluate.add_argument("--reasoning", action="store_true", help="use ChainOfThought")
    evaluate.add_argument("--threads", type=int, default=2)
    evaluate.add_argument("--show", type=int, default=6)
    evaluate.set_defaults(handler=cmd_evaluate)

    compiling = commands.add_parser("compile", help="let an optimiser pick the demos")
    compiling.add_argument("--demos", type=int, default=4, help="bootstrapped demos")
    compiling.add_argument("--labeled", type=int, default=4, help="labelled demos")
    compiling.add_argument("--reasoning", action="store_true")
    compiling.add_argument("--threads", type=int, default=2)
    compiling.add_argument("--show", type=int, default=6)
    compiling.add_argument("--out", default=str(COMPILED_DEFAULT))
    compiling.set_defaults(handler=cmd_compile)

    show = commands.add_parser("show", help="read what a compiled program carries")
    show.add_argument("program", nargs="?", default=str(COMPILED_DEFAULT))
    show.set_defaults(handler=cmd_show)

    prompt = commands.add_parser(
        "prompt", help="classify one line and print the request"
    )
    prompt.add_argument("subject")
    prompt.add_argument("--program", help="a compiled.json to load first")
    prompt.add_argument("--reasoning", action="store_true")
    prompt.set_defaults(handler=cmd_prompt)

    jev_parser = commands.add_parser("jev", help="the same program on Jev")
    jev_commands = jev_parser.add_subparsers(dest="jev_command", required=True)
    replay = argparse.ArgumentParser(add_help=False)
    replay.add_argument(
        "--fixtures", action="store_true", help="replay recorded answers"
    )

    jev_ask = jev_commands.add_parser(
        "ask", parents=[replay], help="one line, every probability"
    )
    jev_ask.add_argument("subject")
    jev_ask.add_argument("--program", help="a jev-compiled.json to load first")
    jev_ask.add_argument(
        "--weight", action="append", default=[], help="type=number, repeatable"
    )
    jev_ask.set_defaults(handler=cmd_jev_ask)

    jev_evaluate = jev_commands.add_parser(
        "evaluate", parents=[replay], help="score it on one split"
    )
    jev_evaluate.add_argument("--split", choices=tuple(SPLITS), default="development")
    jev_evaluate.add_argument("--program", help="a jev-compiled.json to load first")
    jev_evaluate.add_argument(
        "--weight", action="append", default=[], help="type=number, repeatable"
    )
    jev_evaluate.add_argument("--threads", type=int, default=4)
    jev_evaluate.add_argument("--show", type=int, default=6)
    jev_evaluate.set_defaults(handler=cmd_jev_evaluate)

    jev_reanchor = jev_commands.add_parser(
        "reanchor", parents=[replay], help="fit the weights"
    )
    jev_reanchor.add_argument("--threads", type=int, default=4)
    jev_reanchor.add_argument("--out", default=str(JEV_COMPILED_DEFAULT))
    jev_reanchor.set_defaults(handler=cmd_jev_reanchor)

    jev_record = jev_commands.add_parser(
        "record", help="re-record the fixtures (needs a key)"
    )
    jev_record.set_defaults(handler=cmd_jev_record)

    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except jev.FixtureMiss as miss:
        print(f"fixture miss: {miss}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
