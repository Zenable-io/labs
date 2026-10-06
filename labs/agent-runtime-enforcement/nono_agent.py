"""Copyright (c) 2026 Zenable, Inc. Run a command in a nono sandbox from Python, and show what it could not do.

Usage:
    uv run python nono_agent.py -- COMMAND...
    uv run python nono_agent.py --mode landlock -- COMMAND...

The parent stays unsandboxed; the child gets Landlock (and, in the default
seccomp mode, a static seccomp baseline underneath it) before it execs.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from nono_py import (
    AccessMode,
    CapabilitySet,
    is_supported,
    sandboxed_exec,
    support_info,
)

HERE = Path(__file__).resolve().parent


def child_environment() -> list[tuple[str, str]]:
    # Share the CLI profile's allowlist so new sandbox credential aliases
    # cannot silently reach the Python child.
    profile = json.loads((HERE / "nono" / "agent.jsonc").read_text())
    return [
        (name, os.environ[name])
        for name in profile["environment"]["allow_vars"]
        if name in os.environ
    ]


def capabilities() -> CapabilitySet:
    """What the agent may touch. Everything else is denied by omission."""
    caps = CapabilitySet()
    caps.allow_path(str(HERE / "workspace"), AccessMode.READ_WRITE)
    caps.allow_path(str(HERE / "goose"), AccessMode.READ_WRITE)
    # What a dynamically linked binary needs to start at all. nono refuses a
    # grant for a path that does not exist, and the set differs per OS.
    for system in (
        "/usr",
        "/lib",
        "/lib64",
        "/etc",
        str(Path.home() / ".local" / "bin"),
    ):
        if Path(system).exists():
            caps.allow_path(system, AccessMode.READ)
    caps.block_network()
    return caps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "seccomp", "landlock"],
        default="seccomp",
        help="enforcement backend (default: seccomp baseline under Landlock)",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command given after --")

    if not is_supported():
        info = support_info()
        raise SystemExit(f"nono cannot sandbox here: {info.details}")

    caps = capabilities()
    print(caps.summary(), file=sys.stderr)
    result = sandboxed_exec(
        caps,
        command,
        cwd=str(HERE),
        timeout_secs=args.timeout,
        env=child_environment(),
        inherit_env=False,
        enforcement_mode=args.mode,
    )
    # The bindings hand back raw bytes; the child may print anything.
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
