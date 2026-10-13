# Copyright (c) 2026 Zenable, Inc.
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Runtime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    build: tuple[str, ...] = ()
    sources: str = ""
    run: tuple[str, ...]
    checks: tuple[str, ...]
    pythonpath: str = ""
    metrics: tuple[str, ...]


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str
    alpha: int
    beta: int
    events: int


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    purpose: str
    requests: tuple[str, ...]
    expected: tuple[Observation, ...]


class Program(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]
    checks: tuple[str, ...]

    def run(self, mode: str, requests: tuple[str, ...]) -> list[Observation]:
        if mode not in {"history", "design"}:
            raise ValueError("Expected history or design")
        completed = subprocess.run(
            [*self.command, mode],
            cwd=self.cwd,
            env=self.environment,
            input="\n".join(requests) + "\n",
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        observations = []
        for line in completed.stdout.splitlines():
            status, alpha, beta, events = line.split("\t")
            observations.append(
                Observation(
                    status=status, alpha=int(alpha), beta=int(beta), events=int(events)
                )
            )
        if len(observations) != len(requests):
            raise ValueError("The program must return one observation per request")
        return observations


def languages() -> list[str]:
    return sorted(
        path.parent.name for path in (ROOT / "languages").glob("*/runtime.json")
    )


def runtime_for(language: str) -> Runtime:
    if language not in languages():
        raise ValueError(f"Unknown language: {language}")
    return Runtime.model_validate_json(
        (ROOT / "languages" / language / "runtime.json").read_text()
    )


def scenarios() -> list[Scenario]:
    return [
        Scenario.model_validate(item)
        for item in json.loads((ROOT / "scenarios.json").read_text())
    ]


def expand_command(
    arguments: tuple[str, ...], directory: Path, build: str, sources: str
) -> tuple[str, ...]:
    expanded = []
    for argument in arguments:
        if argument == "@sources":
            expanded.extend(str(path) for path in sorted(directory.glob(sources)))
        else:
            expanded.append(argument.format(build=build, python=sys.executable))
    executable = shutil.which(expanded[0])
    if executable is None:
        raise RuntimeError(
            f"Missing runtime: {expanded[0]}. Use the lab's Docker image."
        )
    expanded[0] = executable
    return tuple(expanded)


@contextmanager
def compile_program(language: str) -> Iterator[Program]:
    runtime = runtime_for(language)
    directory = ROOT / "languages" / language
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if runtime.pythonpath:
        environment["PYTHONPATH"] = str(directory / runtime.pythonpath)
    with TemporaryDirectory(prefix="expense-lab-") as build:
        if runtime.build:
            subprocess.run(
                expand_command(runtime.build, directory, build, runtime.sources),
                cwd=directory,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        yield Program(
            command=expand_command(runtime.run, directory, build, runtime.sources),
            cwd=directory,
            environment=environment,
            checks=expand_command(runtime.checks, directory, build, runtime.sources),
        )
