"""Copyright (c) 2026 Zenable, Inc. Load agentwatch into the kernel, run a command, print what its tree did.

Usage (as root, the BPF syscall needs it):
    sudo uv run python agentwatch.py [--kill] [--otlp http://localhost:4318] -- COMMAND...
    sudo uv run python agentwatch.py --deny -- COMMAND...   # adds the LSM hook

The command runs as the invoking user (SUDO_UID), not root, so the agent sees
the same home directory and the same permissions it would without the watch.
"""

import argparse
import os
import signal
import sys
from contextlib import ExitStack
from pathlib import Path
from types import FrameType

import libbpf
import process_scope
import telemetry
from events import decode, render

HERE = Path(__file__).resolve().parent
WATCH_OBJ = HERE / "bpf" / "agentwatch.bpf.o"
DENY_OBJ = HERE / "bpf" / "agentdeny.bpf.o"


def terminate(signum: int, _frame: FrameType | None) -> None:
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--kill",
        action="store_true",
        help="SIGKILL a process in the tree that opens a credential path",
    )
    parser.add_argument(
        "--deny",
        action="store_true",
        help="also load the LSM hook that refuses credential opens",
    )
    parser.add_argument(
        "--otlp",
        metavar="URL",
        help="ship each event as an OpenTelemetry log record to this endpoint",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="print every process on the machine, not only the command's tree",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command given after --")
    if os.geteuid() != 0:
        parser.error("loading a BPF program needs root; run under sudo")
    if not WATCH_OBJ.exists():
        parser.error(f"{WATCH_OBJ.name} is missing; run `make` first")

    with ExitStack() as resources:
        for signum in (signal.SIGTERM, signal.SIGHUP):
            previous = signal.signal(signum, terminate)
            resources.callback(signal.signal, signum, previous)
        emitter = (
            telemetry.Emitter(telemetry.otlp_provider(args.otlp)) if args.otlp else None
        )
        if emitter:
            resources.callback(emitter.shutdown)
        watch = resources.enter_context(libbpf.Object(str(WATCH_OBJ)))
        watch.load()
        deny = (
            resources.enter_context(libbpf.Object(str(DENY_OBJ))) if args.deny else None
        )
        if deny:
            deny.load()
        scope = resources.enter_context(process_scope.create())
        cgroup_id = scope.stat().st_ino
        scope_fd = watch.map_fd("scope_config")
        libbpf.map_set_u64(scope_fd, 0, cgroup_id)
        libbpf.map_set_u64(scope_fd, 1, int(args.all))
        libbpf.map_set_u32(watch.map_fd("watch_config"), 0, int(args.kill))
        print(f"attached: {', '.join(watch.attach_all())}", file=sys.stderr)
        if deny:
            libbpf.map_set_u64(deny.map_fd("scope_config"), 0, cgroup_id)
            print(f"attached: {', '.join(deny.attach_all())}", file=sys.stderr)

        def on_record(record: bytes) -> None:
            event = decode(record)
            print(render(event), flush=True)
            if emitter:
                emitter.emit(event)

        ring = resources.enter_context(libbpf.Ring(watch.map_fd("events"), on_record))
        child = process_scope.launch(command, scope)
        try:
            while child.poll() is None:
                ring.poll(100)
            ring.poll(200)
        finally:
            # Descendants must not outlive the policy, even if the root exits first.
            process_scope.stop(scope)
            child.wait()
        if deny:
            denied = libbpf.map_get_u64(deny.map_fd("denied_count"), 0)
            print(f"lsm denied {denied} credential open(s)", file=sys.stderr)
        return child.returncode


if __name__ == "__main__":
    sys.exit(main())
