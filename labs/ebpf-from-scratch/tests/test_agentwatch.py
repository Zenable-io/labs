# Copyright (c) 2026 Zenable, Inc.
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import agentwatch
import libbpf
import process_scope
import pytest


@pytest.fixture
def command_workspace() -> Iterator[Path]:
    # sudo owns pytest's temp tree; the launched learner must reach its fixtures.
    with tempfile.TemporaryDirectory(prefix="agentwatch-test-") as directory:
        path = Path(directory)
        os.chown(
            path,
            int(os.environ.get("SUDO_UID", os.getuid())),
            int(os.environ.get("SUDO_GID", os.getgid())),
        )
        yield path


def links() -> set[int]:
    result = subprocess.run(
        ["bpftool", "-j", "link", "show"], check=True, capture_output=True, text=True
    )
    return {link["id"] for link in json.loads(result.stdout)}


@pytest.mark.integration
@pytest.mark.kernel
def test_lsm_scopes_descendants_and_preserves_earlier_denials(
    command_workspace: Path,
) -> None:
    credentials = command_workspace / ".aws" / "credentials"
    credentials.parent.mkdir()
    credentials.write_text("decoy")
    before = links()
    with libbpf.Object(str(agentwatch.DENY_OBJ)) as first:
        first.load()
        with libbpf.Object(str(agentwatch.DENY_OBJ)) as second:
            second.load()
            with process_scope.create() as target, process_scope.create() as other:
                libbpf.map_set_u64(
                    first.map_fd("scope_config"), 0, target.stat().st_ino
                )
                libbpf.map_set_u64(
                    second.map_fd("scope_config"), 0, other.stat().st_ino
                )
                first.attach_all()
                second.attach_all()
                assert len(links() - before) == 2
                # A shell fork exercises inheritance; the second hook must keep EPERM.
                child = process_scope.launch(
                    [
                        "sh",
                        "-c",
                        'cat "$1"; result=$?; exit "$result"',
                        "sh",
                        str(credentials),
                    ],
                    target,
                )
                assert child.wait(timeout=10) == 1
                assert credentials.read_text() == "decoy"
                assert libbpf.map_get_u64(first.map_fd("denied_count"), 0) >= 1
                assert libbpf.map_get_u64(second.map_fd("denied_count"), 0) == 0
    assert links() == before
    assert credentials.read_text() == "decoy"


@pytest.mark.integration
@pytest.mark.kernel
def test_kill_stays_scoped_when_observing_all_and_the_ring_is_full(
    command_workspace: Path,
) -> None:
    credentials = command_workspace / ".aws" / "credentials"
    credentials.parent.mkdir()
    credentials.write_text("decoy")
    with libbpf.Object(str(agentwatch.WATCH_OBJ)) as watch:
        watch.load()
        with process_scope.create() as scope:
            scope_fd = watch.map_fd("scope_config")
            libbpf.map_set_u64(scope_fd, 0, scope.stat().st_ino)
            libbpf.map_set_u64(scope_fd, 1, 1)
            libbpf.map_set_u32(watch.map_fd("watch_config"), 0, 1)
            watch.attach_all()
            # No ring consumer: unrelated events exhaust its one MiB capacity.
            for _ in range(5000):
                with open("/dev/null", "rb"):
                    pass
            assert credentials.read_text() == "decoy"
            child = process_scope.launch(["cat", str(credentials)], scope)
            assert child.wait(timeout=10) == -signal.SIGKILL
            assert credentials.read_text() == "decoy"


@pytest.mark.integration
@pytest.mark.kernel
@pytest.mark.parametrize("interrupt", [False, True])
def test_loader_cleans_descendants_and_links_on_exit(
    command_workspace: Path, interrupt: bool
) -> None:
    marker = command_workspace / "child.pid"
    script = (
        f'setsid sleep 60 & printf "%s\\n" "$!" > "$1"; sleep {60 if interrupt else 0}'
    )
    before = links()
    with subprocess.Popen(
        [
            sys.executable,
            agentwatch.__file__,
            "--deny",
            "--",
            "/bin/sh",
            "-c",
            script,
            "sh",
            str(marker),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    ) as loader:
        try:
            deadline = time.monotonic() + 15
            while not marker.exists():
                assert loader.poll() is None, loader.stderr.read()
                assert time.monotonic() < deadline, "command did not start"
                time.sleep(0.02)
            if interrupt:
                loader.terminate()
            _, errors = loader.communicate(timeout=15)
            assert loader.returncode == (143 if interrupt else 0), errors
        finally:
            if loader.poll() is None:
                loader.kill()
                loader.wait()
    pid = int(marker.read_text())
    stat = Path(f"/proc/{pid}/stat")
    assert not stat.exists() or stat.read_text().split()[2] == "Z"
    assert links() == before
    assert not list(Path("/sys/fs/cgroup").glob("agentwatch-*"))


@pytest.mark.unit
def test_termination_unwinds_cleanup() -> None:
    with pytest.raises(SystemExit) as error:
        agentwatch.terminate(signal.SIGTERM, None)
    assert error.value.code == 143
