"""Copyright (c) 2026 Zenable, Inc. A seccomp sandbox with no dependencies: build the filter, install it, exec.

Usage:
    python seccomp_sandbox.py --deny connect [--deny socket] [--action errno|kill|trap] -- COMMAND...
    python seccomp_sandbox.py --deny connect --show

seccomp-bpf runs a tiny classic-BPF program on every system call the process
makes. The program gets a `struct seccomp_data` (syscall number, architecture,
arguments) and returns a verdict. This file assembles that program by hand so
there is nothing between you and what the kernel executes.
"""

import argparse
import ctypes
import errno
import os
import platform
import struct
import sys

from syscalls import number

# Classic BPF instruction classes and modes, from <linux/bpf_common.h>.
BPF_LD = 0x00
BPF_JMP = 0x05
BPF_RET = 0x06
BPF_W = 0x00
BPF_ABS = 0x20
BPF_JEQ = 0x10
BPF_JSET = 0x40
BPF_K = 0x00

# Offsets into struct seccomp_data, from <linux/seccomp.h>.
SECCOMP_DATA_NR = 0
SECCOMP_DATA_ARCH = 4

AUDIT_ARCH_X86_64 = 0xC000003E
X32_SYSCALL_BIT = 0x40000000

SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_TRAP = 0x00030000
SECCOMP_RET_ERRNO = 0x00050000
SECCOMP_RET_ALLOW = 0x7FFF0000

# prctl(2) and seccomp(2) constants.
PR_SET_NO_NEW_PRIVS = 38
SECCOMP_SET_MODE_FILTER = 1
NR_SECCOMP = number("seccomp")

ACTIONS = {
    "errno": SECCOMP_RET_ERRNO | errno.EPERM,
    "kill": SECCOMP_RET_KILL_PROCESS,
    "trap": SECCOMP_RET_TRAP,
}


def stmt(code: int, k: int) -> bytes:
    """One `struct sock_filter` with no jump targets."""
    return struct.pack("HBBI", code, 0, 0, k)


def jump(code: int, k: int, jt: int, jf: int) -> bytes:
    """One `struct sock_filter` that jumps jt/jf instructions on true/false."""
    return struct.pack("HBBI", code, jt, jf, k)


def build_filter(denied: list[int], action: int) -> bytes:
    """Restrict the ABI to native x86_64, then deny the requested calls."""
    if len(denied) > 255:
        raise ValueError("At most 255 denied calls fit the 8-bit jump offsets")
    if any(type(nr) is not int or not 0 <= nr < X32_SYSCALL_BIT for nr in denied):
        raise ValueError("Denied calls must be native x86_64 syscall numbers")
    if action not in ACTIONS.values():
        raise ValueError("Unsupported seccomp action")
    program = [
        stmt(BPF_LD | BPF_W | BPF_ABS, SECCOMP_DATA_ARCH),
        jump(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        stmt(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        stmt(BPF_LD | BPF_W | BPF_ABS, SECCOMP_DATA_NR),
        # x32 shares AUDIT_ARCH_X86_64; its syscall bit bypasses native numbers.
        jump(BPF_JMP | BPF_JSET | BPF_K, X32_SYSCALL_BIT, 0, 1),
        stmt(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
    ]
    for index, nr in enumerate(denied):
        remaining = len(denied) - index - 1
        # true: skip past the remaining compares and the allow, land on action
        program.append(jump(BPF_JMP | BPF_JEQ | BPF_K, nr, remaining + 1, 0))
    program.append(stmt(BPF_RET | BPF_K, SECCOMP_RET_ALLOW))
    program.append(stmt(BPF_RET | BPF_K, action))
    return b"".join(program)


def describe(denied: dict[str, int], action_name: str) -> str:
    """The same program, as the kernel would run it, one instruction per line."""
    lines = [
        "00: ld  [arch]",
        f"01: jeq #0x{AUDIT_ARCH_X86_64:08x} (x86_64), goto 03, else 02",
        "02: ret KILL_PROCESS",
        "03: ld  [nr]",
        f"04: jset #0x{X32_SYSCALL_BIT:08x} (x32), goto 05, else 06",
        "05: ret KILL_PROCESS",
    ]
    names = list(denied)
    for index, name in enumerate(names):
        hit = 6 + len(names) + 1
        lines.append(
            f"{6 + index:02}: jeq #{denied[name]} ({name}), goto {hit:02}, else {7 + index:02}"
        )
    lines.append(f"{6 + len(names):02}: ret ALLOW")
    lines.append(f"{7 + len(names):02}: ret {action_name.upper()}")
    return "\n".join(lines)


class SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def install(program: bytes) -> None:
    """Install the filter on this process; it is inherited by every child.

    no_new_privs first: the kernel refuses a filter from an unprivileged
    process without it, because a filter that returns errno could otherwise
    turn a setuid binary's failed check into a success path.
    """
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise RuntimeError("Installing this lab's filter requires Linux x86_64")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_NO_NEW_PRIVS)")
    buffer = ctypes.create_string_buffer(program, len(program))
    prog = SockFprog(len(program) // 8, ctypes.cast(buffer, ctypes.c_void_p))
    if libc.syscall(NR_SECCOMP, SECCOMP_SET_MODE_FILTER, 0, ctypes.byref(prog)) != 0:
        raise OSError(ctypes.get_errno(), "seccomp(SECCOMP_SET_MODE_FILTER)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--deny",
        action="append",
        default=[],
        metavar="SYSCALL",
        help="syscall name to deny (repeatable)",
    )
    parser.add_argument(
        "--action",
        choices=ACTIONS,
        default="errno",
        help="what a denied call gets (default: errno, EPERM)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="print the filter instead of running anything",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="command to run under the filter, after --",
    )
    args = parser.parse_args(argv)

    denied = {name: number(name) for name in args.deny}
    if not denied:
        parser.error("nothing to deny; pass at least one --deny")
    if args.show:
        print(describe(denied, args.action))
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command given after --")

    install(build_filter(list(denied.values()), ACTIONS[args.action]))
    # exec replaces this interpreter with the command; the filter comes along.
    os.execvp(command[0], command)
    return 1  # unreachable


if __name__ == "__main__":
    sys.exit(main())
