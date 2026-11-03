# Copyright (c) 2026 Zenable, Inc.
import os
from pathlib import Path
from unittest.mock import Mock

import process_scope
import pytest


@pytest.mark.unit
def test_enrolment_failure_kills_child_before_command_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = Mock(pid=999)
    launch = Mock(return_value=child)
    release = Mock()
    monkeypatch.setattr(process_scope.subprocess, "Popen", launch)
    monkeypatch.setattr(process_scope.os, "write", release)
    with pytest.raises(FileNotFoundError):
        process_scope.launch(["true"], tmp_path / "missing")
    child.kill.assert_called_once()
    child.wait.assert_called_once()
    release.assert_not_called()
    assert launch.call_args.args[0][4] == str(os.environ.get("SUDO_UID", os.getuid()))
    assert "preexec_fn" not in launch.call_args.kwargs


@pytest.mark.unit
def test_shutdown_waits_for_descendants_to_leave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cgroup.events").write_text("populated 1\nfrozen 0\n")
    waited = []

    def finish(_duration: float) -> None:
        waited.append(True)
        (tmp_path / "cgroup.events").write_text("populated 0\nfrozen 0\n")

    monkeypatch.setattr(process_scope.time, "sleep", finish)
    process_scope.stop(tmp_path)
    assert waited
    assert (tmp_path / "cgroup.kill").read_text() == "1"


@pytest.mark.unit
def test_shutdown_timeout_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "cgroup.events").write_text("populated 1\n")
    with pytest.raises(TimeoutError, match="processes remain"):
        process_scope.stop(tmp_path, timeout=0)
