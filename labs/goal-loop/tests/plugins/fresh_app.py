# Copyright (c) 2026 Zenable, Inc.
"""Give every test module a freshly imported ledger package.

Module-level state (the catalogue index, the settings object) is thrown away
between modules so one module's imports can't leak into the next.
"""

import importlib
import sys

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    for name in [name for name in sys.modules if name == "ledger" or name.startswith("ledger.")]:
        del sys.modules[name]
    importlib.import_module("ledger")
