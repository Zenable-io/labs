# Copyright (c) 2026 Zenable, Inc.
from collections.abc import Iterator

import pytest
from workshop.runtime import Program, compile_program, languages


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--language", default="all", choices=["all", *languages()])
    parser.addoption(
        "--implementation", default="design", choices=["history", "design"]
    )


@pytest.fixture
def implementation(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("implementation")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "program" in metafunc.fixturenames:
        language = metafunc.config.getoption("language")
        selected = languages() if language == "all" else [language]
        metafunc.parametrize("program", selected, indirect=True, scope="session")


@pytest.fixture(scope="session")
def program(request: pytest.FixtureRequest) -> Iterator[Program]:
    with compile_program(request.param) as compiled:
        yield compiled
