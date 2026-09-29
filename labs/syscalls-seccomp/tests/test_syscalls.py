# Copyright (c) 2026 Zenable, Inc.
import pytest
import syscalls


@pytest.mark.unit
def test_builtin_table_agrees_with_headers_when_present() -> None:
    header = syscalls.from_header()
    for name, number in syscalls.X86_64.items():
        if name in header:
            assert header[name] == number
