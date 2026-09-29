"""Copyright (c) 2026 Zenable, Inc. x86_64 system call numbers, read from the kernel's own header when it is there.

The header is the ground truth (`/usr/include/asm/unistd_64.h`, from
kernel-headers). The table below covers the calls this lab names so the tools
still work on a machine without the headers installed, and the two are checked
against each other whenever the header is present.
"""

import re
from pathlib import Path

UNISTD_64 = Path("/usr/include/asm/unistd_64.h")

# Only the numbers the lab's own filters and profiles refer to.
X86_64 = {
    "read": 0,
    "write": 1,
    "open": 2,
    "close": 3,
    "mmap": 9,
    "socket": 41,
    "connect": 42,
    "sendto": 44,
    "recvfrom": 45,
    "clone": 56,
    "fork": 57,
    "vfork": 58,
    "execve": 59,
    "chmod": 90,
    "prctl": 157,
    "clone3": 435,
    "openat": 257,
    "mkdir": 83,
    "unlink": 87,
    "seccomp": 317,
    "openat2": 437,
}

_DEFINE = re.compile(r"^#define\s+__NR_(\w+)\s+(\d+)\s*$", re.MULTILINE)


def from_header(path: Path = UNISTD_64) -> dict[str, int]:
    """Every syscall the installed kernel headers define, or {} without them."""
    if not path.is_file():
        return {}
    return {name: int(number) for name, number in _DEFINE.findall(path.read_text())}


def table() -> dict[str, int]:
    """The header when present, with the built-in table as the fallback.

    A disagreement between the two is a bug in this file, never something to
    paper over: the kernel is right.
    """
    header = from_header()
    if not header:
        return dict(X86_64)
    for name, number in X86_64.items():
        if name in header and header[name] != number:
            raise RuntimeError(
                f"{name} is {header[name]} in {UNISTD_64} but {number} here; fix syscalls.py"
            )
    return header


def number(name: str) -> int:
    """Resolve one syscall name, raising a readable error for a typo."""
    try:
        return table()[name]
    except KeyError:
        raise SystemExit(f"unknown syscall {name!r}; check `man 2 syscalls`") from None
