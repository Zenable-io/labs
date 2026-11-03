"""Copyright (c) 2026 Zenable, Inc. Keep a command and its descendants inside one root-owned cgroup v2."""

import os
import pwd
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent


def stop(path: Path, timeout: float = 5) -> None:
    """Kill the entire subtree, including children that fork during shutdown."""
    (path / "cgroup.kill").write_text("1")
    deadline = time.monotonic() + timeout
    while "populated 1" in (path / "cgroup.events").read_text().splitlines():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"processes remain in {path}")
        time.sleep(0.01)


@contextmanager
def create() -> Iterator[Path]:
    root = Path("/sys/fs/cgroup")
    with tempfile.TemporaryDirectory(prefix="agentwatch-", dir="/run") as directory:
        mounted = not (root / "cgroup.controllers").exists()
        if mounted:
            # EL8 can keep its v1 controllers; this hierarchy needs none of them.
            root = Path(directory)
            subprocess.run(["mount", "-t", "cgroup2", "none", str(root)], check=True)
        try:
            path = Path(tempfile.mkdtemp(prefix="agentwatch-", dir=root))
            try:
                if not (path / "cgroup.kill").exists():
                    raise RuntimeError("agentwatch requires cgroup.kill (Linux 5.14+)")
                try:
                    yield path
                finally:
                    stop(path)
            finally:
                path.rmdir()
        finally:
            if mounted:
                subprocess.run(["umount", str(root)], check=True)


def launch(command: list[str], scope: Path) -> subprocess.Popen[bytes]:
    uid = int(os.environ.get("SUDO_UID", os.getuid()))
    gid = int(os.environ.get("SUDO_GID", os.getgid()))
    entry = pwd.getpwuid(uid)
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("SUDO_")
    }
    env.update(HOME=entry.pw_dir, USER=entry.pw_name, LOGNAME=entry.pw_name)
    env["PATH"] = f"{entry.pw_dir}/.local/bin:{env.get('PATH', '')}"
    reader, writer = os.pipe()
    child = None
    try:
        # Isolated Python waits before exec: no user startup code can race enrolment.
        child = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                str(HERE / "launch.py"),
                str(uid),
                str(gid),
                ",".join(str(group) for group in os.getgrouplist(entry.pw_name, gid)),
                str(reader),
                *command,
            ],
            cwd=HERE,
            env=env,
            start_new_session=True,
            pass_fds=(reader,),
        )
        (scope / "cgroup.procs").write_text(str(child.pid))
        os.write(writer, b"1")
        return child
    except BaseException:
        if child is not None:
            child.kill()
            child.wait()
        raise
    finally:
        os.close(reader)
        os.close(writer)
