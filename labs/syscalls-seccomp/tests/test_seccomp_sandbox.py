# Copyright (c) 2026 Zenable, Inc.
import struct

import pytest
import seccomp_sandbox


def instructions(program: bytes) -> list[tuple[int, int, int, int]]:
    return [
        struct.unpack("HBBI", program[i : i + 8]) for i in range(0, len(program), 8)
    ]


def verdict(program: bytes, arch: int, syscall: int) -> int:
    data = struct.pack("II", syscall, arch)
    ops = instructions(program)
    offset = 0
    accumulator = 0
    while offset < len(ops):
        code, on_true, on_false, value = ops[offset]
        if code == 0x20:
            accumulator = struct.unpack_from("I", data, value)[0]
        elif code == 0x15:
            offset += on_true if accumulator == value else on_false
        elif code == 0x45:
            offset += on_true if accumulator & value else on_false
        elif code == 0x06:
            return value
        else:
            raise AssertionError(f"Unsupported classic-BPF opcode: {code:#x}")
        offset += 1
    raise AssertionError("Filter fell through without a verdict")


@pytest.mark.unit
@pytest.mark.parametrize("action", seccomp_sandbox.ACTIONS.values())
def test_filter_decisions_reject_foreign_abis_and_enforce_native_calls(
    action: int,
) -> None:
    program = seccomp_sandbox.build_filter([42, 41], action)
    arch = seccomp_sandbox.AUDIT_ARCH_X86_64
    assert verdict(program, arch, 42) == action
    assert verdict(program, arch, 41) == action
    assert verdict(program, arch, 1) == seccomp_sandbox.SECCOMP_RET_ALLOW
    assert verdict(program, 0x40000003, 42) == seccomp_sandbox.SECCOMP_RET_KILL_PROCESS
    for syscall in (1, 41, 42, 521):
        assert (
            verdict(program, arch, syscall | 0x40000000)
            == seccomp_sandbox.SECCOMP_RET_KILL_PROCESS
        )


@pytest.mark.unit
def test_filter_layout_denies_listed_calls_and_allows_the_rest() -> None:
    program = seccomp_sandbox.build_filter([42, 41], seccomp_sandbox.ACTIONS["errno"])
    ops = instructions(program)
    assert len(ops) == 6 + 2 + 2
    # arch check, kill on mismatch
    assert ops[0] == (
        seccomp_sandbox.BPF_LD | seccomp_sandbox.BPF_W | seccomp_sandbox.BPF_ABS,
        0,
        0,
        4,
    )
    assert ops[1][3] == seccomp_sandbox.AUDIT_ARCH_X86_64
    assert ops[2][3] == seccomp_sandbox.SECCOMP_RET_KILL_PROCESS
    # first denied number jumps over the second compare and the allow
    assert ops[6] == (
        seccomp_sandbox.BPF_JMP | seccomp_sandbox.BPF_JEQ | seccomp_sandbox.BPF_K,
        2,
        0,
        42,
    )
    assert ops[7] == (
        seccomp_sandbox.BPF_JMP | seccomp_sandbox.BPF_JEQ | seccomp_sandbox.BPF_K,
        1,
        0,
        41,
    )
    assert ops[8][3] == seccomp_sandbox.SECCOMP_RET_ALLOW
    assert ops[9][3] == seccomp_sandbox.SECCOMP_RET_ERRNO | 1


@pytest.mark.unit
def test_describe_matches_the_assembled_program() -> None:
    text = seccomp_sandbox.describe({"connect": 42}, "kill")
    assert "jset #0x40000000 (x32), goto 05, else 06" in text
    assert "jeq #42 (connect), goto 08, else 07" in text
    assert text.splitlines()[-1] == "08: ret KILL"


@pytest.mark.unit
def test_filter_accepts_maximum_reachable_jump() -> None:
    program = seccomp_sandbox.build_filter(
        list(range(255)), seccomp_sandbox.ACTIONS["errno"]
    )
    for syscall in (0, 127, 254):
        assert (
            verdict(program, seccomp_sandbox.AUDIT_ARCH_X86_64, syscall)
            == seccomp_sandbox.ACTIONS["errno"]
        )


@pytest.mark.unit
@pytest.mark.parametrize("denied", [list(range(256)), [-1], [0x40000000], [True]])
def test_filter_rejects_unrepresentable_calls(denied: list[int]) -> None:
    with pytest.raises(ValueError):
        seccomp_sandbox.build_filter(denied, seccomp_sandbox.ACTIONS["errno"])


@pytest.mark.unit
def test_install_rejects_other_architectures_before_any_syscall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seccomp_sandbox.platform, "machine", lambda: "aarch64")
    with pytest.raises(RuntimeError, match="Linux x86_64"):
        seccomp_sandbox.install(b"")


@pytest.mark.unit
def test_filter_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="action"):
        seccomp_sandbox.build_filter([42], 123)
