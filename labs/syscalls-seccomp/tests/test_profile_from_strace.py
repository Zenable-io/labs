# Copyright (c) 2026 Zenable, Inc.
import profile_from_strace
import pytest

SAMPLE_SUMMARY = """\
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 40.00    0.004000         100        40           read
 30.00    0.003000         150        20         3 openat
 20.00    0.002000         200        10           connect
 10.00    0.001000          50        20           write
------ ----------- ----------- --------- --------- ----------------
100.00    0.010000                    90         3 total
"""


@pytest.mark.unit
def test_summary_parser_takes_every_named_row() -> None:
    names = profile_from_strace.syscalls_from_summary(SAMPLE_SUMMARY)
    assert names == {"read", "openat", "connect", "write"}


@pytest.mark.unit
def test_profile_is_an_allowlist_with_the_container_baseline() -> None:
    result = profile_from_strace.profile({"read", "connect"})
    assert result["defaultAction"] == "SCMP_ACT_ERRNO"
    names = result["syscalls"][0]["names"]
    assert names == sorted(names)
    assert "connect" in names
    assert "execve" in names
    assert "chmod" not in names
