"""Copyright (c) 2026 Zenable, Inc. A Landlock sandbox with no dependencies: build the ruleset, add the grants, restrict, exec.

Usage:
    uv run python landlock.py --allow workspace --read /usr --read /etc -- COMMAND...
    uv run python landlock.py --show

Landlock is a Linux security module an unprivileged process applies to itself.
Three system calls do all of it: create a ruleset naming the kinds of file
access it will police, add one rule per granted path, then restrict the
calling process. From that point every file access by this process and every
child is checked against the grants, and nothing can loosen it again.
"""

import argparse
import ctypes
import os
import platform
import struct
import sys

# Syscall numbers, identical on x86_64 and aarch64 (both take the generic table
# for these three).
NR_LANDLOCK_CREATE_RULESET = 444
NR_LANDLOCK_ADD_RULE = 445
NR_LANDLOCK_RESTRICT_SELF = 446

LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
LANDLOCK_RULE_PATH_BENEATH = 1

# Access rights, from <linux/landlock.h>, in the order each ABI added them.
ACCESS_FS = {
    "execute": 1 << 0,
    "write_file": 1 << 1,
    "read_file": 1 << 2,
    "read_dir": 1 << 3,
    "remove_dir": 1 << 4,
    "remove_file": 1 << 5,
    "make_char": 1 << 6,
    "make_dir": 1 << 7,
    "make_reg": 1 << 8,
    "make_sock": 1 << 9,
    "make_fifo": 1 << 10,
    "make_block": 1 << 11,
    "make_sym": 1 << 12,
    "refer": 1 << 13,
    "truncate": 1 << 14,
    "ioctl_dev": 1 << 15,
}
# The newest right each ABI version understands. Handling a right the kernel
# does not know fails the ruleset, so the mask is cut to what the kernel offers.
ABI_LAST_RIGHT = {
    1: "make_sym",
    2: "refer",
    3: "truncate",
    4: "truncate",
    5: "ioctl_dev",
}

READ_RIGHTS = ACCESS_FS["execute"] | ACCESS_FS["read_file"] | ACCESS_FS["read_dir"]

PR_SET_NO_NEW_PRIVS = 38

SUPPORTED_MACHINES = ("x86_64", "aarch64")

libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long


def handled_access(abi: int) -> int:
    """Every filesystem right this kernel's Landlock can police."""
    last = ABI_LAST_RIGHT[min(abi, max(ABI_LAST_RIGHT))]
    mask = 0
    for name, bit in ACCESS_FS.items():
        mask |= bit
        if name == last:
            break
    return mask


def ruleset_attr(handled: int) -> bytes:
    """One `struct landlock_ruleset_attr`, filesystem rights only."""
    return struct.pack("Q", handled)


def path_beneath_attr(allowed: int, parent_fd: int) -> bytes:
    """One packed `struct landlock_path_beneath_attr`."""
    return struct.pack("<Qi", allowed, parent_fd)


def _check(result: int, what: str) -> int:
    if result < 0:
        err = ctypes.get_errno()
        raise OSError(err, f"{what}: {os.strerror(err)}")
    return result


def abi_version() -> int:
    """Ask the kernel which Landlock ABI it offers; 0 when it offers none."""
    result = libc.syscall(
        NR_LANDLOCK_CREATE_RULESET,
        None,
        ctypes.c_size_t(0),
        ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
    )
    return result if result > 0 else 0


def create_ruleset(handled: int) -> int:
    attr = ctypes.create_string_buffer(ruleset_attr(handled), 8)
    return _check(
        libc.syscall(
            NR_LANDLOCK_CREATE_RULESET, attr, ctypes.c_size_t(8), ctypes.c_uint32(0)
        ),
        "landlock_create_ruleset",
    )


def add_path(ruleset_fd: int, path: str, allowed: int) -> None:
    parent_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        attr = ctypes.create_string_buffer(path_beneath_attr(allowed, parent_fd), 12)
        _check(
            libc.syscall(
                NR_LANDLOCK_ADD_RULE,
                ruleset_fd,
                ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
                attr,
                ctypes.c_uint32(0),
            ),
            f"landlock_add_rule {path}",
        )
    finally:
        os.close(parent_fd)


def restrict_self(ruleset_fd: int) -> None:
    # Landlock refuses to restrict a process that could still gain privilege
    # through a setuid binary, so no_new_privs comes first.
    _check(libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0), "prctl(PR_SET_NO_NEW_PRIVS)")
    _check(
        libc.syscall(NR_LANDLOCK_RESTRICT_SELF, ruleset_fd, ctypes.c_uint32(0)),
        "landlock_restrict_self",
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="PATH",
        help="grant read and write beneath PATH",
    )
    parser.add_argument(
        "--read",
        action="append",
        default=[],
        metavar="PATH",
        help="grant read and execute beneath PATH",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="print the ABI and the rights the ruleset would police, then exit",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    args.command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not args.show and not args.command:
        parser.error("no command given after --")
    return args


def describe(abi: int) -> str:
    handled = handled_access(abi)
    rights = ", ".join(name for name, bit in ACCESS_FS.items() if handled & bit)
    return f"Landlock ABI {abi}\nhandled rights ({handled:#x}): {rights}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if platform.system() != "Linux" or platform.machine() not in SUPPORTED_MACHINES:
        raise SystemExit(
            f"landlock.py needs Linux on one of {SUPPORTED_MACHINES}, not {platform.system()} {platform.machine()}"
        )
    abi = abi_version()
    if abi == 0:
        raise SystemExit(
            "this kernel offers no Landlock: check for 'landlock' in /sys/kernel/security/lsm"
        )
    if args.show:
        print(describe(abi))
        return 0

    handled = handled_access(abi)
    ruleset_fd = create_ruleset(handled)
    try:
        for path in args.read:
            add_path(ruleset_fd, path, READ_RIGHTS)
        for path in args.allow:
            add_path(ruleset_fd, path, handled)
        restrict_self(ruleset_fd)
    finally:
        os.close(ruleset_fd)
    os.execvp(args.command[0], args.command)


if __name__ == "__main__":
    sys.exit(main())
