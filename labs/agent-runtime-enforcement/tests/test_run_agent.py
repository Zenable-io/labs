# Copyright (c) 2026 Zenable, Inc.
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RIG = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_local_agent_does_not_inherit_credentials_or_provider_overrides(
    tmp_path: Path,
) -> None:
    home = tmp_path / "learner home"
    binary = home / ".local/bin/goose"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "print(json.dumps({'env': dict(os.environ), 'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n"
        "sys.stderr.write('test goose error')\n"
        "sys.exit(17)\n"
    )
    binary.chmod(0o755)
    inherited = {
        "HOME": str(home),
        "PATH": f"{Path(sys.executable).parent}:{os.defpath}",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "GOOSE_PROVIDER": "cloud-provider",
        "GOOSE_PATH_ROOT": "/unrelated/config",
    }
    for name in (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "TYPESAFE_API_KEY",
        "OPENAI_API_KEY",
        "AWS_SESSION_TOKEN",
        "FUTURE_PROVIDER_TOKEN",
    ):
        inherited[name] = "test-inherited-credential"

    result = subprocess.run(
        ["bash", str(RIG / "run-agent.sh"), "read workspace/VERSION"],
        cwd=tmp_path,
        env=inherited,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 17
    assert result.stderr == "test goose error"
    child = json.loads(result.stdout)
    assert child["cwd"] == str(RIG)
    assert child["args"] == ["run", "--no-session", "-t", "read workspace/VERSION"]
    expected = {
        "HOME": str(home),
        "PATH": f"{home}/.local/bin:{inherited['PATH']}",
        "LANG": inherited["LANG"],
        "TERM": inherited["TERM"],
        "GOOSE_PATH_ROOT": str(RIG / "goose"),
    }
    assert {
        key: value for key, value in child["env"].items() if key in inherited
    } == expected
