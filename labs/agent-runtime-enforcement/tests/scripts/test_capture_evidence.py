# Copyright (c) 2026 Zenable, Inc.
import os
import shutil
import subprocess
from pathlib import Path

import pytest

RIG = Path(__file__).resolve().parents[2]


@pytest.fixture
def capture_checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    rig = tmp_path / "lab checkout" / "rig"
    scripts = rig / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(RIG / "scripts/capture-evidence.sh", scripts)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for command in (
        "uv",
        "sudo",
        "strace",
        "make",
        "llvm-objdump",
        "clang",
        "bpftool",
        "bpftrace",
        "docker",
        "nono",
        "goose",
    ):
        stub = binaries / command
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    return rig, {"PATH": f"{binaries}:{os.defpath}", "HOME": str(tmp_path)}


@pytest.mark.integration
@pytest.mark.parametrize("location", ["published", "source", "absolute"])
def test_capture_resolves_every_output_from_the_rig(
    capture_checkout: tuple[Path, dict[str, str]], tmp_path: Path, location: str
) -> None:
    rig, env = capture_checkout
    evidence = rig / "evidence"
    if location == "source":
        env["EVIDENCE_DIR"] = "../evidence"
        evidence = rig.parent / "evidence"
    elif location == "absolute":
        evidence = tmp_path / "custom evidence"
        env["EVIDENCE_DIR"] = str(evidence)

    result = subprocess.run(
        ["bash", str(rig / "scripts/capture-evidence.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (evidence / "versions.txt").is_file()
    assert len(list(evidence.iterdir())) > 1
    assert not (tmp_path / "evidence").exists()
    if location != "source":
        assert not (rig.parent / "evidence").exists()


@pytest.mark.integration
def test_capture_stops_when_evidence_directory_cannot_be_created(
    capture_checkout: tuple[Path, dict[str, str]], tmp_path: Path
) -> None:
    rig, env = capture_checkout
    blocked = tmp_path / "not a directory"
    blocked.write_text("existing file\n")
    env["EVIDENCE_DIR"] = str(blocked)

    result = subprocess.run(
        ["bash", str(rig / "scripts/capture-evidence.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert blocked.read_text() == "existing file\n"
