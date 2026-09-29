# Copyright (c) 2026 Zenable, Inc.
import pytest
from workshop.runtime import Program, Scenario, scenarios


@pytest.mark.integration
@pytest.mark.parametrize("scenario", scenarios(), ids=lambda scenario: scenario.name)
def test_every_entrypoint_preserves_the_contract(
    program: Program, scenario: Scenario, implementation: str
) -> None:
    assert program.run(implementation, scenario.requests) == list(scenario.expected)


@pytest.mark.integration
@pytest.mark.parametrize("channel", ["web", "batch"])
def test_malformed_input_leaves_state_unchanged(
    program: Program, channel: str, implementation: str
) -> None:
    observed = program.run(
        implementation,
        (f"{channel}\talpha\talice\tapprover\talpha\tshared\t-1\tstandard\tr1",),
    )
    assert observed[0].status == "invalid_input"
    assert (observed[0].alpha, observed[0].beta, observed[0].events) == (
        10_000,
        20_000,
        0,
    )
