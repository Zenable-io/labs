# Copyright (c) 2026 Zenable, Inc.
import subprocess

import pytest
from workshop.runtime import Program


@pytest.mark.integration
def test_policy_and_concurrency_contracts(program: Program) -> None:
    result = subprocess.run(
        program.checks,
        cwd=program.cwd,
        env=program.environment,
        check=False,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
