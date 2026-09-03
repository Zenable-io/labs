"""GitHub Actions annotation utilities for CI workflow commands.

Emits ``::warning``/``::error``/``::notice`` workflow commands to stdout, and
no-ops outside GitHub Actions so local runs stay readable.

Trimmed from ``zenable_monorepo.annotations``: this repository never annotates a
column range or opens a ``::group::``, so those are omitted rather than carried
as dead code.

See https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/workflow-commands-for-github-actions
"""

import os
from pathlib import Path


def _in_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _escape_message(value: str) -> str:
    """Percent-encode the characters GitHub reserves in message text."""
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    """Property values additionally escape the ``:`` and ``,`` delimiters."""
    return _escape_message(value).replace(":", "%3A").replace(",", "%2C")


def _annotate(
    level: str,
    message: str,
    *,
    file: str | Path | None = None,
    title: str | None = None,
) -> str:
    """Format and (in CI) print one annotation. Returns the formatted string."""
    parts = []
    if file is not None:
        parts.append(f"file={_escape_property(str(file))}")
    if title is not None:
        parts.append(f"title={_escape_property(title)}")
    prop_str = f" {','.join(parts)}" if parts else ""
    result = f"::{level}{prop_str}::{_escape_message(message)}"

    if _in_github_actions():
        print(result)

    return result


def warning(
    message: str, *, file: str | Path | None = None, title: str | None = None
) -> str:
    """Emit a ``::warning`` annotation. Returns the formatted string."""
    return _annotate("warning", message, file=file, title=title)


def error(
    message: str, *, file: str | Path | None = None, title: str | None = None
) -> str:
    """Emit an ``::error`` annotation. Returns the formatted string."""
    return _annotate("error", message, file=file, title=title)


def notice(
    message: str, *, file: str | Path | None = None, title: str | None = None
) -> str:
    """Emit a ``::notice`` annotation. Returns the formatted string."""
    return _annotate("notice", message, file=file, title=title)
