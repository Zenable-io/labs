# Copyright (c) 2026 Zenable, Inc. `package = false` keeps this rig out of the venv, so nothing would make
# `jev_router` importable from the tests. A conftest here puts the rig root on
# the path, which is what pytest does with the directory a root conftest lives
# in.
