# Copyright (c) 2026 Zenable, Inc.
import argparse
import math
from importlib.metadata import version

import lizard

from workshop.runtime import ROOT, languages, runtime_for


def crap(complexity: int, coverage_percent: float) -> float:
    if (
        complexity < 1
        or not math.isfinite(coverage_percent)
        or not 0 <= coverage_percent <= 100
    ):
        raise ValueError(
            "Complexity must be positive and coverage must be between 0 and 100"
        )
    return complexity**2 * (1 - coverage_percent / 100) ** 3 + complexity


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure complexity and explore CRAP coverage assumptions"
    )
    parser.add_argument("language", choices=languages())
    arguments = parser.parse_args()
    directory = ROOT / "languages" / arguments.language
    print(f"Cyclomatic complexity measured with Lizard {version('lizard')}")
    print("CRAP columns assume basis-path coverage; they are NOT measured coverage.")
    print("function\tC\tCRAP@0%\tCRAP@50%\tCRAP@100%")
    for filename in runtime_for(arguments.language).metrics:
        result = lizard.analyze_file(str(directory / filename))
        for function in result.function_list:
            complexity = function.cyclomatic_complexity
            scores = "\t".join(
                f"{crap(complexity, coverage):.2f}" for coverage in (0, 50, 100)
            )
            print(f"{filename}:{function.name}\t{complexity}\t{scores}")


if __name__ == "__main__":
    main()
