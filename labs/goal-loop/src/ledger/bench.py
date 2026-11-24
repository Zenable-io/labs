# Copyright (c) 2026 Zenable, Inc.
"""Time the test suite and print one line: how many tests passed, and the wall-clock seconds."""

import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run() -> tuple[int, float]:
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-m", "not goal", "tests"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"bench: the tests failed after {elapsed:.1f}s")
    match = re.search(r"(\d+) passed", result.stdout)
    passed = int(match.group(1)) if match else 0
    return passed, elapsed


if __name__ == "__main__":
    passed, elapsed = run()
    print(f"bench: {passed} tests passed in {elapsed:.1f}s")
