# Copyright (c) 2026 Zenable, Inc.
"""The lab's target: the whole suite, still passing, under the time limit."""

import pytest

from ledger.bench import run

TARGET_SECONDS = 10.0
TESTS_EXPECTED = 63


@pytest.mark.goal
@pytest.mark.integration
def test_suite_passes_under_the_target() -> None:
    passed, elapsed = run()
    assert passed >= TESTS_EXPECTED, f"only {passed} tests passed; the suite must stay whole"
    assert elapsed < TARGET_SECONDS, f"the suite took {elapsed:.1f}s; target is {TARGET_SECONDS}s"
