# Copyright (c) 2026 Zenable, Inc.
import platform
import struct
import subprocess
import sys
from pathlib import Path

import landlock
import pytest

RIG = Path(__file__).resolve().parents[1]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("abi", "highest"),
    [
        (1, "make_sym"),
        (2, "refer"),
        (3, "truncate"),
        (4, "truncate"),
        (5, "ioctl_dev"),
        (6, "ioctl_dev"),
    ],
)
def test_handled_access_stops_at_what_the_kernel_offers(abi: int, highest: str) -> None:
    handled = landlock.handled_access(abi)
    assert handled & landlock.ACCESS_FS[highest]
    newer = [
        bit
        for name, bit in landlock.ACCESS_FS.items()
        if bit > landlock.ACCESS_FS[highest]
    ]
    assert all(not handled & bit for bit in newer)
    assert handled & landlock.READ_RIGHTS == landlock.READ_RIGHTS


@pytest.mark.unit
def test_kernel_structs_pack_to_their_c_sizes() -> None:
    assert len(landlock.ruleset_attr(0x1FFF)) == 8
    allowed, parent_fd = struct.unpack(
        "<Qi", landlock.path_beneath_attr(landlock.READ_RIGHTS, 7)
    )
    assert (allowed, parent_fd) == (landlock.READ_RIGHTS, 7)
    assert len(landlock.path_beneath_attr(0, 0)) == 12


@pytest.mark.unit
def test_parse_args_separates_grants_from_the_command() -> None:
    args = landlock.parse_args(
        [
            "--allow",
            "workspace",
            "--read",
            "/usr",
            "--read",
            "/etc",
            "--",
            "cat",
            "--",
            "x",
        ]
    )
    assert args.allow == ["workspace"]
    assert args.read == ["/usr", "/etc"]
    assert args.command == ["cat", "--", "x"]
    with pytest.raises(SystemExit):
        landlock.parse_args(["--allow", "workspace"])


@pytest.mark.unit
def test_describe_stops_at_the_abis_last_right() -> None:
    text = landlock.describe(3)
    assert text.startswith("Landlock ABI 3")
    assert "truncate" in text and "ioctl_dev" not in text


def _landlock_available() -> bool:
    lsm = Path("/sys/kernel/security/lsm")
    if platform.system() == "Linux" and lsm.exists():
        return "landlock" in lsm.read_text()
    return platform.system() == "Linux" and landlock.abi_version() > 0


@pytest.mark.integration
@pytest.mark.skipif(
    not _landlock_available(), reason="needs a Linux kernel with Landlock"
)
def test_restricted_child_reads_the_grant_and_nothing_else(tmp_path: Path) -> None:
    granted = tmp_path / "granted"
    granted.mkdir()
    (granted / "ok").write_text("ok\n")
    secret = tmp_path / "secret"
    secret.write_text("no\n")
    system = [p for p in ("/usr", "/lib", "/lib64", "/etc") if Path(p).exists()]
    reads = [arg for path in system for arg in ("--read", path)]
    base = [
        sys.executable,
        str(RIG / "landlock.py"),
        "--allow",
        str(granted),
        *reads,
        "--",
    ]

    allowed = subprocess.run(
        [*base, "cat", str(granted / "ok")], capture_output=True, text=True, check=False
    )
    assert (allowed.returncode, allowed.stdout) == (0, "ok\n"), allowed.stderr

    denied = subprocess.run(
        [*base, "cat", str(secret)], capture_output=True, text=True, check=False
    )
    assert denied.returncode != 0
    assert "Permission denied" in denied.stderr
