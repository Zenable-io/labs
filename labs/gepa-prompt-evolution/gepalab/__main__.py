"""Copyright (c) 2026 Zenable, Inc. The commands this lab runs.

Every command that scores a prompt asks the hosted model, one call per line,
and says at the end how many calls it made. `--fixtures` replays the answers
and reflections of a real run this rig recorded instead, so the whole lab also
works with no key. `record` is the keyed run that writes those fixtures.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from gepa.optimize_anything import (
    EngineConfig,
    GEPAConfig,
    ReflectionConfig,
    TrackingConfig,
    optimize_anything,
)

from gepalab import classify, runs, workshop
from gepalab.classify import (
    BACKGROUND,
    OBJECTIVE,
    SEED_PROMPT,
    SPLITS,
    FixtureMiss,
    Scorer,
    evaluate,
    report,
    score,
)
from gepalab.steps import LiveReflection, RecordedReflection, StepObserver
from gepalab.triage import TRAIN, VALIDATION

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
RECORDED_ANSWERS = "recorded.json"
RECORDED_RUN = "recorded_run.json"
REPLAY = "recorded answers (no API calls)"


def _live_model(requested: str | None) -> str:
    """Prefer the sandbox's allowed model, otherwise a lightweight model."""
    if requested:
        return requested
    sandbox_model = os.environ.get("ZENABLE_SANDBOX_MODEL")
    if os.environ.get("OPENROUTER_API_KEY"):
        return f"openrouter/{sandbox_model or 'google/gemini-2.5-flash-lite'}"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai/gpt-5.4-nano"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY"):
        return "anthropic/claude-haiku-4-5-20251001"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini/gemini-3.5-flash-lite"
    raise SystemExit(
        "no model is configured. Put OPENROUTER_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY "
        "or GEMINI_API_KEY in ~/.env and open a new terminal, or pass "
        "--model with a LiteLLM model name. Without one, add --fixtures to "
        "replay a recorded run instead."
    )


def _configure(args: argparse.Namespace) -> Scorer:
    if args.fixtures:
        scorer = Scorer.replay(FIXTURE_DIR / RECORDED_ANSWERS)
        print(f"replaying {REPLAY}\n")
    else:
        scorer = Scorer.live(_live_model(args.model))
        print(f"scoring with {scorer.model}\n")
    return classify.configure(scorer)


def _print_scores(title: str, prompt: str) -> None:
    print(title)
    for name, examples in SPLITS.items():
        print(f"  {name:<11}{score(prompt, examples):>7.1%}  ({len(examples)} lines)")


def _print_saved_scores(title: str, scores: dict[str, float]) -> None:
    print(title)
    for name, examples in SPLITS.items():
        print(f"  {name:<11}{scores[name]:>7.1%}  ({len(examples)} lines)")


def _print_misses(prompt: str, limit: int) -> None:
    outcomes = [outcome for outcome in report(prompt) if not outcome.correct]
    if not outcomes:
        print("\nevery line is labelled correctly")
        return
    print(f"\n{len(outcomes)} lines are still wrong, the first {limit}:")
    for outcome in outcomes[:limit]:
        answered = outcome.answered or "(no label)"
        print(f"  {outcome.line[:96]}")
        print(f"    expected {outcome.expected}, answered {answered}: {outcome.reason}")


def _print_prompt(title: str, prompt: str) -> None:
    print(title)
    for line in prompt.splitlines():
        print(f"  {line}")


def cmd_baseline(args: argparse.Namespace) -> int:
    _configure(args)
    prompt = args.prompt or SEED_PROMPT
    _print_prompt("prompt:", prompt)
    print()
    _print_scores("exact-match score by split", prompt)
    _print_misses(prompt, args.misses)
    return 0


def _evolve(
    args: argparse.Namespace, scorer: Scorer
) -> tuple[runs.SavedRun, LiveReflection | RecordedReflection]:
    if args.fixtures:
        recorded = classify.Recordings.model_validate_json(
            (FIXTURE_DIR / RECORDED_ANSWERS).read_text()
        )
        reflection: LiveReflection | RecordedReflection = RecordedReflection(
            replies=recorded.reflections
        )
    else:
        kwargs = {
            "max_tokens": args.reflection_tokens,
            "num_retries": 0,
            **classify.no_thinking(scorer.model),
        }
        reflection = LiveReflection(model=scorer.model, kwargs=kwargs)
    run_dir = Path(args.out).resolve()
    if (run_dir / "gepa").exists():
        raise SystemExit(
            "run directory already contains a search; choose a fresh --out directory"
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    observer = StepObserver(
        log_path=run_dir / "optimizer.log",
        pause=args.pause,
        refinements=args.refinements,
        verbose=args.verbose,
    )
    print(
        f"limits: {args.refinements} refinements, {args.budget} evaluations, {args.reflection_tokens} output tokens per reflection"
    )
    print(f"writing {args.out}\n")

    # Keep held-out examples outside the optimiser so final scores remain independent.
    result = optimize_anything(
        SEED_PROMPT,
        evaluator=evaluate,
        dataset=list(TRAIN),
        valset=list(VALIDATION),
        objective=OBJECTIVE,
        background=BACKGROUND,
        config=GEPAConfig(
            engine=EngineConfig(
                max_metric_calls=args.budget,
                max_candidate_proposals=args.refinements,
                max_workers=args.concurrency,
                frontier_type="instance",
                use_cloudpickle=False,
                run_dir=str(run_dir / "gepa"),
                display_progress_bar=False,
            ),
            reflection=ReflectionConfig(
                reflection_lm=reflection,
                reflection_minibatch_size=args.reflect_on,
            ),
            tracking=TrackingConfig(logger=observer),
            callbacks=[observer],
            stop_callbacks=observer,
        ),
    )

    model = REPLAY if args.fixtures else scorer.model
    saved = runs.save(result, run_dir / "run.json", seed=SEED_PROMPT, model=model)
    print()
    _print_saved_scores("seed", saved.seed_scores)
    print()
    _print_saved_scores("best candidate", saved.scores)
    print()
    _print_prompt("best candidate:", saved.best_candidate)
    print(f"\nsaved {Path(args.out) / 'run.json'}")
    if isinstance(reflection, LiveReflection):
        print(f"{len(reflection.replies)} reflection calls")
    return saved, reflection


def cmd_evolve(args: argparse.Namespace) -> int:
    _evolve(args, _configure(args))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    """One keyed pass over everything the lab replays, written to the fixtures."""
    args.fixtures = False
    args.pause = False
    scorer = _configure(args)
    for prompt in (SEED_PROMPT, workshop.DEFINITIONS.prompt, workshop.RULES.prompt):
        report(prompt)
    workshop.show_merge()
    print()
    saved, reflection = _evolve(args, scorer)
    # A replay stopped after fewer refinements saves a different best candidate,
    # and saving scores it on every split, so every kept candidate is scored on
    # every line here.
    for kept in saved.lineage:
        report(kept.text)
    run_path = FIXTURE_DIR / RECORDED_RUN
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    run_path.write_text((Path(args.out) / "run.json").read_text())
    classify.license_sidecar(run_path)
    classify.write_recordings(
        scorer.recordings(tuple(reflection.replies)), FIXTURE_DIR / RECORDED_ANSWERS
    )
    print(
        f"\nrecorded {len(scorer.answers)} answers and "
        f"{len(reflection.replies)} reflections to {FIXTURE_DIR}"
    )
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    _configure(args)
    # A house-rule line: the seed misses it on every run, where a retried error flips between runs.
    example = next(item for item in TRAIN if "staging db-primary" in item.line)
    value, feedback = evaluate(SEED_PROMPT, example)
    _print_prompt("candidate:", SEED_PROMPT)
    print(f"score: {value:.0f}\n")
    for name, content in feedback.items():
        print(f"{name}: {content}")
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    _configure(args)
    workshop.select(args.seed)
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    _configure(args)
    workshop.show_merge()
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    path = Path(args.run) if args.run else FIXTURE_DIR / RECORDED_RUN
    saved = runs.load(path)
    print(f"run {saved.name}, scored with {saved.model}")
    print(f"{saved.evaluations} evaluations, {saved.frontier_size} candidates kept\n")
    _print_saved_scores("seed", saved.seed_scores)
    print()
    _print_saved_scores("best candidate", saved.scores)
    print()
    _print_prompt("seed:", saved.seed)
    print()
    _print_prompt("best candidate:", saved.best_candidate)
    if args.lineage:
        print("\nwhat the search kept, in the order it found them:")
        for index, candidate in enumerate(saved.lineage):
            print(f"  {index}. [{candidate.validation:.1%}]")
            for line in candidate.text.splitlines():
                print(f"     {line}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    _configure(args)
    path = Path(args.prompt)
    prompt = path.read_text().strip() if path.is_file() else args.prompt
    _print_prompt("prompt:", prompt)
    print()
    _print_scores("exact-match score by split", prompt)
    _print_misses(prompt, args.misses)
    return 0


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.home() / ".env", override=True)
    parser = argparse.ArgumentParser(prog="gepalab", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    scoring = argparse.ArgumentParser(add_help=False)
    scoring.add_argument(
        "--fixtures",
        action="store_true",
        help="replay recorded answers without API calls",
    )
    scoring.add_argument(
        "--model", help="LiteLLM model name for scoring and reflection"
    )
    misses = argparse.ArgumentParser(add_help=False)
    misses.add_argument(
        "--misses", type=int, default=6, help="how many wrong lines to print"
    )
    limits = argparse.ArgumentParser(add_help=False)
    limits.add_argument(
        "--budget", type=_positive_int, default=96, help="evaluation stopping threshold"
    )
    limits.add_argument(
        "--refinements", type=_positive_int, default=3, help="maximum proposal attempts"
    )
    limits.add_argument(
        "--concurrency", type=_positive_int, default=classify.CONCURRENCY
    )
    limits.add_argument(
        "--reflect-on",
        type=_positive_int,
        default=4,
        help="scored lines per reflection",
    )
    limits.add_argument(
        "--reflection-tokens",
        type=_positive_int,
        default=1024,
        help="reflection output cap",
    )
    limits.add_argument(
        "--verbose", action="store_true", help="also print the full optimiser log"
    )

    baseline = commands.add_parser(
        "baseline", parents=[scoring, misses], help="score the seed prompt"
    )
    baseline.add_argument("--prompt", help="score this prompt instead of the seed")
    baseline.set_defaults(handler=cmd_baseline)

    evolve = commands.add_parser(
        "evolve", parents=[scoring, limits], help="let GEPA rewrite the prompt"
    )
    evolve.add_argument(
        "--pause", action="store_true", help="wait for Enter between refinements"
    )
    evolve.add_argument("--out", default="runs/prompt")
    evolve.set_defaults(handler=cmd_evolve)

    record = commands.add_parser(
        "record", parents=[scoring, limits], help="re-record the fixtures (needs a key)"
    )
    record.add_argument("--out", default="runs/record")
    record.set_defaults(handler=cmd_record)

    show = commands.add_parser("show", help="read a saved run")
    show.add_argument(
        "run", nargs="?", help="path to run.json (default: the recorded one)"
    )
    show.add_argument(
        "--lineage", action="store_true", help="print every kept candidate"
    )
    show.set_defaults(handler=cmd_show)

    scorer = commands.add_parser(
        "score",
        parents=[scoring, misses],
        help="score any prompt, from a file or inline",
    )
    scorer.add_argument("prompt")
    scorer.set_defaults(handler=cmd_score)

    feedback = commands.add_parser(
        "feedback", parents=[scoring], help="inspect one training failure"
    )
    feedback.set_defaults(handler=cmd_feedback)
    selection = commands.add_parser(
        "select", parents=[scoring], help="sample from prepared Pareto candidates"
    )
    selection.add_argument("--seed", type=int, default=0, help="sampling random seed")
    selection.set_defaults(handler=cmd_select)
    merging = commands.add_parser(
        "merge", parents=[scoring], help="combine improvements to two prompt components"
    )
    merging.set_defaults(handler=cmd_merge)

    args = parser.parse_args(argv)
    if args.command in {"evolve", "record"} and args.reflect_on > len(TRAIN):
        parser.error(f"--reflect-on must be at most {len(TRAIN)}")
    try:
        status = int(args.handler(args))
    except FixtureMiss as miss:
        print(f"fixture miss: {miss}", file=sys.stderr)
        return 2
    if args.command != "show" and not args.fixtures:
        print(f"\n{classify.scorer().calls} model calls")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
