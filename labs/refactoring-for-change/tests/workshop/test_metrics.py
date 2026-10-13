# Copyright (c) 2026 Zenable, Inc.
import pytest
from workshop.metrics import crap


@pytest.mark.unit
@pytest.mark.parametrize(("coverage", "expected"), [(0, 110), (50, 22.5), (100, 10)])
def test_crap_uses_percent_coverage(coverage: float, expected: float) -> None:
    assert crap(10, coverage) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("complexity", "coverage"), [(0, 50), (1, -1), (1, 101), (1, float("nan"))]
)
def test_crap_refuses_invalid_inputs(complexity: int, coverage: float) -> None:
    with pytest.raises(ValueError):
        crap(complexity, coverage)
