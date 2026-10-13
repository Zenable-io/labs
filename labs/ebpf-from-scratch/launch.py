"""Copyright (c) 2026 Zenable, Inc. Wait for cgroup enrolment before running any learner-controlled code."""

import os
import sys


def main(argv: list[str]) -> int:
    uid, gid = int(argv[0]), int(argv[1])
    groups = [int(group) for group in argv[2].split(",")] if argv[2] else []
    # sudo's uv interpreter can live below /root. Drop privileges only after
    # this isolated helper has started, before reading the gate or user code.
    if os.geteuid() == 0:
        os.setgroups(groups)
    elif set(os.getgroups()) != set(groups):
        raise PermissionError("cannot set the invoking user's supplementary groups")
    os.setgid(gid)
    os.setuid(uid)
    descriptor = int(argv[3])
    try:
        ready = os.read(descriptor, 1)
    finally:
        os.close(descriptor)
    if ready != b"1":
        return 125
    os.execvpe(argv[4], argv[4:], os.environ)
    return 125


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
