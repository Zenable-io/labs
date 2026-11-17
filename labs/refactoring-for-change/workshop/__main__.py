# Copyright (c) 2026 Zenable, Inc.
import argparse
import subprocess
import sys

from workshop.runtime import compile_program, languages, scenarios


def main() -> int:
    available = {scenario.name: scenario for scenario in scenarios()}
    parser = argparse.ArgumentParser(
        description="Run a synthetic expense-service scenario"
    )
    parser.add_argument("language", choices=languages())
    parser.add_argument("mode", choices=["history", "design"])
    parser.add_argument("scenario", choices=list(available))
    parser.add_argument(
        "--check", action="store_true", help="Compare with the required behaviour"
    )
    arguments = parser.parse_args()
    scenario = available[arguments.scenario]
    try:
        with compile_program(arguments.language) as program:
            observations = program.run(arguments.mode, scenario.requests)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Unable to run the lab: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stderr, file=sys.stderr)
        return 2
    print(f"{arguments.language} / {arguments.mode} / {scenario.name}")
    print("status\talpha\tbeta\taudit events")
    for observation in observations:
        print(
            f"{observation.status}\t{observation.alpha}\t{observation.beta}\t{observation.events}"
        )
    if arguments.check:
        if observations != list(scenario.expected):
            print(f"FAIL: {scenario.purpose}")
            return 1
        print(f"PASS: {scenario.purpose}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
