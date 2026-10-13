"""Copyright (c) 2026 Zenable, Inc. Decode agentwatch's ring buffer records and follow one process tree.

Pure Python, no kernel involved, so the shape of an event and the rule for
"is this pid one of the agent's" can be tested anywhere.
"""

import socket
import struct
from enum import IntEnum

from pydantic import BaseModel

COMM_BYTES = 16
PATH_MAX_BYTES = 256

# Must match `struct event` in bpf/agentwatch.bpf.c: four u32 then two byte arrays.
EVENT_STRUCT = struct.Struct(f"<IIII{COMM_BYTES}s{PATH_MAX_BYTES}s")


class Kind(IntEnum):
    FORK = 1
    EXEC = 2
    OPEN = 3
    CONNECT = 4
    DENIED = 5


class Event(BaseModel):
    kind: Kind
    pid: int
    ppid: int
    uid: int
    comm: str
    # Decoded from the raw data field: a path, or "host:port" for connect.
    detail: str


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode(errors="replace")


def _sockaddr(raw: bytes) -> str:
    """Render the sockaddr `connect` was given, for the families we care about."""
    if len(raw) < 2:
        return ""
    family = struct.unpack_from("<H", raw)[0]
    if family == socket.AF_INET and len(raw) >= 8:
        port = struct.unpack_from("!H", raw, 2)[0]
        return f"{socket.inet_ntop(socket.AF_INET, raw[4:8])}:{port}"
    if family == socket.AF_INET6 and len(raw) >= 24:
        port = struct.unpack_from("!H", raw, 2)[0]
        return f"[{socket.inet_ntop(socket.AF_INET6, raw[8:24])}]:{port}"
    if family == socket.AF_UNIX:
        return f"unix:{_cstr(raw[2:])}"
    return f"family={family}"


def decode(record: bytes) -> Event:
    kind, pid, ppid, uid, comm, data = EVENT_STRUCT.unpack_from(record)
    detail = _sockaddr(data) if kind == Kind.CONNECT else _cstr(data)
    return Event(
        kind=Kind(kind), pid=pid, ppid=ppid, uid=uid, comm=_cstr(comm), detail=detail
    )


class ProcessTree:
    """Which pids descend from the one we started with.

    Fork events grow the set; everything else is checked against it. The agent
    forks a shell, the shell forks cat and curl, and none of those exec before
    they fork, so following forks is the only way to own the whole tree.
    """

    def __init__(self, root_pid: int) -> None:
        self.pids: set[int] = {root_pid}

    def observe(self, event: Event) -> bool:
        """Record a fork if it belongs to us; return whether the event is ours."""
        if event.kind == Kind.FORK:
            if event.ppid in self.pids:
                self.pids.add(event.pid)
                return True
            return False
        return event.pid in self.pids


def render(event: Event) -> str:
    """One line per event, the way the lab prints them."""
    verb = {
        Kind.FORK: "fork   ",
        Kind.EXEC: "exec   ",
        Kind.OPEN: "open   ",
        Kind.CONNECT: "connect",
        Kind.DENIED: "DENIED ",
    }[event.kind]
    where = event.detail if event.kind != Kind.FORK else f"child {event.pid}"
    return f"{verb} pid={event.pid:<7} ppid={event.ppid:<7} {event.comm:<16} {where}"
