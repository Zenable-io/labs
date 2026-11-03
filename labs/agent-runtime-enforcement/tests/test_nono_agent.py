# Copyright (c) 2026 Zenable, Inc.
from unittest.mock import Mock

import nono_agent
import pytest


@pytest.mark.unit
def test_main_forwards_only_profile_environment_and_preserves_child_result(
    monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    for name in (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "TYPESAFE_API_KEY",
        "OPENAI_API_KEY",
        "AWS_SESSION_TOKEN",
        "FUTURE_PROVIDER_TOKEN",
    ):
        monkeypatch.setenv(name, "test-inherited-credential")
    monkeypatch.setenv("HOME", "/home/learner")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr(nono_agent, "is_supported", lambda: True)
    caps = Mock()
    caps.summary.return_value = "test capabilities"
    monkeypatch.setattr(nono_agent, "capabilities", lambda: caps)
    execute = Mock(
        return_value=Mock(
            stdout=b"child output\n", stderr=b"child error\n", exit_code=17
        )
    )
    monkeypatch.setattr(nono_agent, "sandboxed_exec", execute)

    assert (
        nono_agent.main(
            ["--mode", "landlock", "--timeout", "3", "--", "cat", "workspace/VERSION"]
        )
        == 17
    )

    execute.assert_called_once_with(
        caps,
        ["cat", "workspace/VERSION"],
        cwd=str(nono_agent.HERE),
        timeout_secs=3.0,
        env=[("HOME", "/home/learner"), ("PATH", "/usr/bin:/bin"), ("LANG", "C.UTF-8")],
        inherit_env=False,
        enforcement_mode="landlock",
    )
    output = capsysbinary.readouterr()
    assert output.out == b"child output\n"
    assert output.err == b"test capabilities\nchild error\n"
