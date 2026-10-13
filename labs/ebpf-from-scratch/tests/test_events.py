# Copyright (c) 2026 Zenable, Inc.
import socket
import struct

import pytest
from events import EVENT_STRUCT, Event, Kind, ProcessTree, decode, render
from telemetry import attributes, severity


def record(
    kind: Kind, pid: int, ppid: int, comm: str = "cat", data: bytes = b""
) -> bytes:
    return EVENT_STRUCT.pack(
        kind, pid, ppid, 1000, comm.encode().ljust(16, b"\0"), data.ljust(256, b"\0")
    )


@pytest.mark.unit
def test_open_event_decodes_the_path():
    event = decode(record(Kind.OPEN, 42, 7, data=b"decoys/.aws/credentials"))
    assert event == Event(
        kind=Kind.OPEN,
        pid=42,
        ppid=7,
        uid=1000,
        comm="cat",
        detail="decoys/.aws/credentials",
    )


@pytest.mark.unit
def test_connect_event_renders_ipv4_sockaddr():
    addr = (
        struct.pack("<H", socket.AF_INET)
        + struct.pack("!H", 443)
        + socket.inet_aton("93.184.216.34")
    )
    event = decode(record(Kind.CONNECT, 42, 7, comm="curl", data=addr))
    assert event.detail == "93.184.216.34:443"
    assert attributes(event)["network.peer.address"] == "93.184.216.34"
    assert attributes(event)["network.peer.port"] == 443


@pytest.mark.unit
def test_connect_event_renders_ipv6_sockaddr():
    addr = (
        struct.pack("<H", socket.AF_INET6)
        + struct.pack("!H", 11434)
        + b"\0" * 4
        + socket.inet_pton(socket.AF_INET6, "::1")
    )
    event = decode(record(Kind.CONNECT, 42, 7, comm="goose", data=addr))
    assert event.detail == "[::1]:11434"


@pytest.mark.unit
def test_tree_follows_forks_and_ignores_strangers():
    tree = ProcessTree(root_pid=100)
    assert tree.observe(decode(record(Kind.FORK, 101, 100, comm="bash")))
    assert tree.observe(decode(record(Kind.FORK, 102, 101, comm="bash")))
    assert not tree.observe(decode(record(Kind.FORK, 555, 1, comm="sshd")))
    assert tree.observe(decode(record(Kind.OPEN, 102, 101, data=b"/etc/hosts")))
    assert not tree.observe(decode(record(Kind.OPEN, 555, 1, data=b"/etc/hosts")))


@pytest.mark.unit
def test_denied_events_are_warnings_with_the_file_path():
    event = decode(record(Kind.DENIED, 42, 7, data=b"/home/x/decoys/.aws/credentials"))
    assert severity(event).name == "WARN"
    assert attributes(event)["file.path"].endswith(".aws/credentials")
    assert render(event).startswith("DENIED ")
