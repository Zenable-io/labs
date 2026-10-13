"""Copyright (c) 2026 Zenable, Inc. The commands this lab runs.

`baseline` and `show` need nothing but Python, so the whole measurement side of
the lab works with no key at all. `evolve` is the one command that calls a
model, and it calls only the reflection model: the thing being scored is a
regular expression, and applying one costs nothing.
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from gepa.optimize_anything import (
    EngineConfig,
    GEPAConfig,
    ReflectionConfig,
    TrackingConfig,
    optimize_anything,
)

from gepalab import runs
from gepalab.loglines import TRAIN, VALIDATION
from gepalab.regex_task import (
    BACKGROUND,
    OBJECTIVE,
    SEED_PATTERN,
    SPLITS,
    evaluate,
    report,
    score,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _reflection_model(requested: str | None) -> str:
    """The LiteLLM model GEPA reflects with, or a message naming what to set.

    A Zenable sandbox's key is an OpenRouter key, and it also fills
    OPENAI_API_KEY pointed at OpenRouter, so it has to be recognised first and
    asked for the model the sandbox names. After it, the order matches GEPA's
    own, so a learner who follows its docs lands on the same model.
    """
    if requested:
        return requested
    sandbox_model = os.environ.get("ZENABLE_SANDBOX_MODEL")
    if os.environ.get("OPENROUTER_API_KEY") and sandbox_model:
        return f"openrouter/{sandbox_model}"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai/gpt-5.1"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY"):
        return "anthropic/claude-sonnet-5-5"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini/gemini-2.5-pro"
    raise SystemExit(
        "no reflection model is configured. Put OPENAI_API_KEY, ANTHROPIC_API_KEY "
        "or GEMINI_API_KEY in ~/.env and open a new terminal, or pass "
        "--reflection-model with a LiteLLM model name. Without one, run "
        "`python -m gepalab show` to read a recorded run instead."
    )


def _print_scores(title: str, pattern: str) -> None:
    print(title)
    for name, examples in SPLITS.items():
        print(f"  {name:<11}{score(pattern, examples):>7.1%}  ({len(examples)} lines)")


def _print_misses(pattern: str, limit: int) -> None:
    outcomes = [outcome for outcome in report(pattern) if not outcome.correct]
    if not outcomes:
        print("\nevery line is captured exactly")
        return
    print(f"\n{len(outcomes)} lines are still wrong, the first {limit}:")
    for outcome in outcomes[:limit]:
        expected = outcome.expected or "(nothing)"
        captured = outcome.captured or "(nothing)"
        print(f"  {outcome.line[:96]}")
        print(f"    expected {expected!r}, captured {captured!r}")


def cmd_baseline(args: argparse.Namespace) -> int:
    pattern = args.pattern or SEED_PATTERN
    print(f"pattern: {pattern}\n")
    _print_scores("exact-match score by split", pattern)
    _print_misses(pattern, args.misses)
    return 0


def cmd_evolve(args: argparse.Namespace) -> int:
    model = _reflection_model(args.reflection_model)
    run_dir = Path(args.out).resolve()
    print(f"reflecting with {model}, budget {args.budget} evaluations")
    print(f"writing {run_dir}\n")

    # `dataset` plus `valset` is GEPA's generalization mode: it proposes against
    # minibatches of the training lines and keeps candidates by how they do on
    # lines it did not reflect over. The held-out split never reaches GEPA at
    # all -- this command scores it afterwards, so a candidate cannot be chosen
    # by the split that is supposed to check the choice.
    result = optimize_anything(
        SEED_PATTERN,
        evaluator=evaluate,
        dataset=list(TRAIN),
        valset=list(VALIDATION),
        objective=OBJECTIVE,
        background=BACKGROUND,
        config=GEPAConfig(
            engine=EngineConfig(
                max_metric_calls=args.budget,
                max_workers=args.concurrency,
                run_dir=str(run_dir / "gepa"),
                display_progress_bar=True,
            ),
            # How many scored lines the reflection model reads before it
            # writes the next candidate. GEPA defaults to three, and three
            # failures out of forty is not enough of the problem to see the
            # shape of it: proposals come back tuned to whichever line was in
            # front of them.
            reflection=ReflectionConfig(
                reflection_lm=model,
                reflection_minibatch_size=args.reflect_on,
                # A reflection that runs out of tokens mid-sentence is handed
                # back as a candidate anyway, and an empty or half-written
                # pattern scores zero on everything. Providers differ on what
                # they give you by default, so this says it rather than
                # inheriting it.
                reflection_lm_kwargs={"max_tokens": args.reflection_tokens},
            ),
            tracking=TrackingConfig(),
        ),
    )

    saved = runs.save(result, run_dir / "run.json", seed=SEED_PATTERN, model=model)
    print()
    _print_scores("seed", SEED_PATTERN)
    print()
    _print_scores("best candidate", saved.best_candidate)
    print(f"\nbest candidate:\n  {saved.best_candidate}")
    print(f"\nsaved {run_dir / 'run.json'}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    path = Path(args.run) if args.run else FIXTURE_DIR / "regex_run.json"
    saved = runs.load(path)
    print(f"run {saved.name}, reflected with {saved.model}")
    print(f"{saved.evaluations} evaluations, {saved.frontier_size} candidates kept\n")
    _print_scores("seed", saved.seed)
    print()
    _print_scores("best candidate", saved.best_candidate)
    print(f"\nseed:\n  {saved.seed}")
    print(f"\nbest candidate:\n  {saved.best_candidate}")
    if args.lineage:
        print("\nwhat the search kept, in the order it found them:")
        for index, candidate in enumerate(saved.lineage):
            print(f"  {index}. [{candidate.validation:.1%}] {candidate.text}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    path = Path(args.pattern)
    pattern = path.read_text().strip() if path.is_file() else args.pattern
    print(f"pattern: {pattern}\n")
    _print_scores("exact-match score by split", pattern)
    _print_misses(pattern, args.misses)
    return 0


def _add_misses(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--misses", type=int, default=6, help="how many wrong lines to print"
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.home() / ".env", override=True)
    parser = argparse.ArgumentParser(prog="gepalab", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    baseline = commands.add_parser("baseline", help="score the seed pattern")
    baseline.add_argument("--pattern", help="score this pattern instead of the seed")
    _add_misses(baseline)
    baseline.set_defaults(handler=cmd_baseline)

    evolve = commands.add_parser("evolve", help="let GEPA rewrite the pattern")
    evolve.add_argument("--budget", type=int, default=120, help="maximum evaluations")
    evolve.add_argument("--reflection-model", help="LiteLLM model name for reflection")
    evolve.add_argument("--concurrency", type=int, default=8)
    evolve.add_argument(
        "--reflect-on", type=int, default=8, help="scored lines per reflection"
    )
    evolve.add_argument(
        "--reflection-tokens", type=int, default=4000, help="reflection output cap"
    )
    evolve.add_argument("--name", default="regex")
    evolve.add_argument("--out", default="runs/regex")
    evolve.set_defaults(handler=cmd_evolve)

    show = commands.add_parser("show", help="read a saved run")
    show.add_argument(
        "run", nargs="?", help="path to run.json (default: the recorded one)"
    )
    show.add_argument(
        "--lineage", action="store_true", help="print every kept candidate"
    )
    show.set_defaults(handler=cmd_show)

    scoring = commands.add_parser(
        "score", help="score any pattern, from a file or inline"
    )
    scoring.add_argument("pattern")
    _add_misses(scoring)
    scoring.set_defaults(handler=cmd_score)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
