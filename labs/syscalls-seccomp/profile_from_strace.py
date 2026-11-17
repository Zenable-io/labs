"""Copyright (c) 2026 Zenable, Inc. Turn an `strace -f -c` summary into a Docker seccomp profile.

Usage:
    strace -f -c -o agent.strace ./run-agent.sh
    python profile_from_strace.py agent.strace > agent-seccomp.json

Everything the traced run called is allowed; everything else fails with
EPERM. That is the shape of Docker's own default profile, built from one
observed run instead of years of upstream judgement, which is exactly why the
lab then shows it breaking.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# The last column of every row in strace's summary table is the syscall name;
# the header, the separator and the total row have no such name.
_ROW = re.compile(r"^\s*[\d.]+\s+[\d.]+\s+\d+\s+\d+(?:\s+\d+)?\s+([a-z_0-9]+)\s*$")

# Calls the container runtime's own startup makes before the traced program
# runs. runc execs the entrypoint under the profile, so these have to be
# allowed even though a trace of the program alone never sees them. The list
# was found by starting a container under a profile and removing entries one
# at a time until it stopped booting; the second group is what other runc
# versions have needed, kept so the profile survives a Docker upgrade.
CONTAINER_BASELINE = (
    "capget",
    "capset",
    "chdir",
    "execve",
    "exit_group",
    "fstatfs",
    "futex",
    "getcwd",
    "getdents64",
    "getppid",
    "openat2",
    "prctl",
    "rt_sigreturn",
    "setgid",
    "setgroups",
    "setuid",
    "statx",
    # glibc 2.28 programs use stat/fstat/lstat, Go programs like runc use
    # newfstatat; a profile built from one must still start the other.
    "fstat",
    "lstat",
    "newfstatat",
    "stat",
    # SQLite removes its journal file when it creates a database; a traced run
    # against a database that already existed never shows it.
    "unlink",
    "unlinkat",
    # runc version margin
    "close_range",
    "dup3",
    "epoll_create1",
    "epoll_ctl",
    "epoll_pwait",
    "exit",
    "fcntl",
    "getpid",
    "gettid",
    "keyctl",
    "mount",
    "pipe2",
    "pivot_root",
    "rseq",
    "rt_sigaction",
    "rt_sigprocmask",
    "sched_getaffinity",
    "set_robust_list",
    "set_tid_address",
    "sethostname",
    "setns",
    "sigaltstack",
    "tgkill",
    "umount2",
    "unshare",
    "wait4",
)


def syscalls_from_summary(text: str) -> set[str]:
    """Every syscall name in an `strace -c` summary."""
    names = {match.group(1) for match in map(_ROW.match, text.splitlines()) if match}
    # The footer row has the same column shape with `total` where a name goes.
    return names - {"total"}


def profile(names: set[str]) -> dict:
    """A Docker/OCI seccomp profile that allows exactly `names`."""
    return {
        "defaultAction": "SCMP_ACT_ERRNO",
        "defaultErrnoRet": 1,
        "architectures": ["SCMP_ARCH_X86_64"],
        "syscalls": [
            {
                "names": sorted(names | set(CONTAINER_BASELINE)),
                "action": "SCMP_ACT_ALLOW",
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("summary", type=Path, help="file written by strace -f -c -o")
    args = parser.parse_args(argv)

    names = syscalls_from_summary(args.summary.read_text())
    if not names:
        raise SystemExit(
            f"{args.summary}: no syscall rows found; was it written with strace -c?"
        )
    json.dump(profile(names), sys.stdout, indent=2)
    print()
    print(f"{len(names)} observed syscalls allowed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
