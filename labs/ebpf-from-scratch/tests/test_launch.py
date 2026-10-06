# Copyright (c) 2026 Zenable, Inc.
import os
import pwd
import subprocess
import sys
from pathlib import Path

import launch
import process_scope
import pytest


@pytest.mark.integration
@pytest.mark.parametrize("release", [b"1", b""])
def test_command_waits_for_enrolment_and_refuses_closed_gate(
    tmp_path: Path, release: bytes
) -> None:
    marker = tmp_path / "executed"
    reader, writer = os.pipe()
    with subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-S",
            launch.__file__,
            str(os.getuid()),
            str(os.getgid()),
            ",".join(str(group) for group in os.getgroups()),
            str(reader),
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
            str(marker),
        ],
        pass_fds=(reader,),
    ) as child:
        try:
            assert not marker.exists()
            assert child.poll() is None
            os.write(writer, release)
        finally:
            os.close(reader)
            os.close(writer)
        assert child.wait(timeout=10) == (0 if release else 125)
    assert marker.exists() == bool(release)


@pytest.mark.integration
@pytest.mark.kernel
def test_private_sudo_interpreter_can_launch_as_invoker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invoker = pwd.getpwnam("nobody")
    private = tmp_path / "root-only"
    private.mkdir(mode=0o700)
    interpreter = private / "python"
    interpreter.symlink_to(sys.executable)
    monkeypatch.setattr(process_scope.sys, "executable", str(interpreter))
    monkeypatch.setenv("SUDO_UID", str(invoker.pw_uid))
    monkeypatch.setenv("SUDO_GID", str(invoker.pw_gid))
    with process_scope.create() as scope:
        child = process_scope.launch(
            [
                "/bin/sh",
                "-c",
                '[ "$(id -u)" = "$1" ] && [ "$(id -g)" = "$2" ] '
                '&& [ "$HOME" = "$3" ] && ! test -r "$4" && ! test -w "$5"',
                "sh",
                str(invoker.pw_uid),
                str(invoker.pw_gid),
                invoker.pw_dir,
                str(interpreter),
                str(scope / "cgroup.procs"),
            ],
            scope,
        )
        assert child.wait(timeout=10) == 0
