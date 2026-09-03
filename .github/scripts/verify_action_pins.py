#!/usr/bin/env python3
"""Reachability verification for hash-pinned GitHub Actions.

pinact's ``--verify-comment`` proves a pin's ``# vX.Y.Z`` comment still resolves
to the SHA next to it. It cannot prove that SHA belongs to the repository it is
attributed to: a tag created against a commit pushed to a *fork* resolves just
as cleanly, which is the imposter-commit half of
https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23

Reachability from a named branch is what separates the two, and it is the one
check pinact has no equivalent for. The pin-actions job runs this after pinning,
so a poisoned pin fails the job rather than landing in the weekly PR.

The min-age cooldown does not cover this. pinact compares the commit's
*committer date*, which is attacker-controlled — backdating a commit walks
straight through a 7-day window.

This also stands in for a per-PR ``zizmor unpinned-uses`` gate: a ``uses:`` that
is not SHA-pinned is reported as a failure here rather than skipped, so the
weekly run catches anything reintroduced by hand.
"""

import argparse
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import yaml

from supply_chain import annotations
from supply_chain.github import verify_commit_on_branch

log = logging.getLogger("verify_action_pins")

_SHA_LENGTH = 40
_SHA_CHARS = frozenset("0123456789abcdef")

# `uses:` values naming something other than an upstream GitHub repository:
# a local action, a local reusable workflow, or a container image.
_NON_UPSTREAM_PREFIXES = ("./", "../", "docker://")


def _iter_uses(node: object) -> Iterator[str]:
    """Yield every ``uses:`` value in a parsed workflow or action document.

    Walks the whole document rather than the shapes we know today
    (``jobs.*.steps[]``, ``runs.steps[]``, ``jobs.*.uses``) so a shape we have
    not thought of cannot quietly escape verification.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                yield value
            else:
                yield from _iter_uses(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_uses(item)


def _is_sha(ref: str) -> bool:
    return len(ref) == _SHA_LENGTH and set(ref) <= _SHA_CHARS


def collect_files(paths: list[Path]) -> list[Path]:
    """Expand the requested paths into the YAML documents to inspect."""
    files: set[Path] = set()
    for path in paths:
        if path.is_dir():
            files.update(path.rglob("*.yml"))
            files.update(path.rglob("*.yaml"))
        elif path.is_file():
            files.add(path)
    return sorted(files)


def find_pinned_actions(
    files: list[Path],
) -> tuple[dict[tuple[str, str, str], set[str]], list[str]]:
    """Map every pinned upstream action to the files that reference it.

    Parsing is YAML-aware rather than line-based so quoting, indentation and
    block style cannot change the answer.

    :return: ``{(owner, repo, sha): {file, ...}}`` plus a list of upstream refs
        that are not SHA-pinned. Those are reported rather than skipped so this
        check is never silently partial.
    """
    pins: dict[tuple[str, str, str], set[str]] = {}
    unpinned: list[str] = []

    for file_path in files:
        document = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        for uses in _iter_uses(document):
            if uses.startswith(_NON_UPSTREAM_PREFIXES):
                continue
            name, _, ref = uses.partition("@")
            if not ref:
                continue
            parts = name.split("/")
            if len(parts) < 2:
                continue
            owner, repo = parts[0], parts[1]
            if not _is_sha(ref):
                unpinned.append(f"{file_path}: {name}@{ref} is not pinned to a commit")
                continue
            pins.setdefault((owner, repo, ref), set()).add(str(file_path))

    return pins, unpinned


def verify_reachable(pins: dict[tuple[str, str, str], set[str]]) -> list[str]:
    """Confirm each pinned commit is reachable from a branch in its repository.

    Deduplicated by commit: one SHA referenced from many call sites resolves
    identically for all of them, so it is verified once to stay inside the
    hourly GitHub API budget.
    """
    failures: list[str] = []

    for (owner, repo, sha), locations in sorted(pins.items()):
        try:
            branch = verify_commit_on_branch(owner, repo, sha)
        except Exception as exc:
            failures.append(
                f"{owner}/{repo}@{sha} is not reachable from any branch: {exc} "
                f"Referenced by: {', '.join(sorted(locations))}"
            )
            continue
        log.info("%s/%s@%s reachable from %s", owner, repo, sha, branch)

    return failures


def verify_action_pins(paths: list[Path]) -> int:
    """Verify every pinned action under ``paths``. Returns a process exit code."""
    files = collect_files(paths)
    if not files:
        log.error("No workflow or action files found under: %s", paths)
        return 1
    log.info("Inspecting %d file(s) for pinned actions", len(files))

    pins, unpinned = find_pinned_actions(files)
    log.info("Found %d distinct pinned commit(s)", len(pins))

    failures = unpinned + verify_reachable(pins)
    if failures:
        for failure in failures:
            log.error(failure)
            annotations.error(failure, title="action-pin-not-reachable")
        return 1

    log.info("Every pinned action is reachable from an upstream branch")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Verify hash-pinned GitHub Actions resolve to commits reachable upstream"
    )
    parser.add_argument(
        "--path",
        type=Path,
        action="append",
        required=True,
        help="File or directory to inspect; repeatable. Directories are searched recursively",
    )
    sys.exit(verify_action_pins(parser.parse_args().path))
