#!/usr/bin/env python3
"""Update a pinned version in one or more files, gated on cooldown and integrity.

Resolves the newest upstream version that has cleared its supply-chain cooldown,
verifies it (for GitHub sources, that the tag maps to a commit reachable from a
branch of the repo it claims to come from), and rewrites the pin via an explicit
search/replacement regex pair.

Trimmed from ``scripts/update_file.py`` in Zenable-io/next-gen-governance to the
two sources this repository actually pins from. Adding another (PyPI, npm, a
GitHub tag with no release) means a new ``_select_*`` branch and a source type;
the cooldown and downgrade machinery is source-agnostic already.

Deliberately omitted, with reasons:
- Default patterns per file type. Every pin here is a bespoke line in a
  compose file, Dockerfile, or README, so an inferred pattern would be a
  guess. Both patterns are required arguments instead.
- ``--include-prerelease``. Nothing here should track a prerelease, and the
  anchored tag regex rejects them on shape even when upstream mislabels one.
"""

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from supply_chain import docker_hub, github
from supply_chain.cooldown import check_cooldown, is_within_cooldown

log = logging.getLogger("update_file")

# ---------------------------------------------------------------------------
# Version comparison for the --no-downgrade gate
# ---------------------------------------------------------------------------
#
# The gate exists so a refresh can never replace a pinned version with something
# strictly older. SemVer 2.0 ordering: numeric parts compared numerically,
# stable > prerelease at the same release level, numeric prerelease identifiers
# below alphanumeric ones.

_VERSION_RE = re.compile(r"\d+(?:\.\d+){0,3}(?:-[\w.+-]+)?(?:\+[\w.-]+)?")

# Hex digits are also decimal digits, so a hash pin's SHA would otherwise read as
# a version (`8177...` -> 8177) and wedge the downgrade gate shut. Full-length
# only, so a date-shaped version like `20260803` is never mistaken for one.
_GIT_SHA_RE = re.compile(r"\b(?:[0-9a-f]{40}|[0-9a-f]{64})\b")


def _parse_version(version: str) -> tuple:
    """Return a sortable tuple for a SemVer-ish version string."""
    stripped = version.lstrip("vV")
    main, _, _build = stripped.partition("+")
    base, _, pre = main.partition("-")
    release_parts: list[int] = []
    for piece in base.split("."):
        if not piece.isdigit():
            break
        release_parts.append(int(piece))
    # Pad to 3 so 1.0 == 1.0.0 and short versions sort against full ones.
    while len(release_parts) < 3:
        release_parts.append(0)
    if not pre:
        # No prerelease -> higher precedence than any prerelease at the same release.
        return (tuple(release_parts), 1, ())
    pre_parts: list[tuple] = []
    for piece in pre.split("."):
        # Per SemVer, numeric prerelease identifiers rank below alphanumeric ones.
        pre_parts.append((0, int(piece)) if piece.isdigit() else (1, piece))
    return (tuple(release_parts), 0, tuple(pre_parts))


def _is_version_upgrade(current: str, candidate: str) -> bool:
    """True iff ``candidate`` is strictly newer than ``current``."""
    return _parse_version(current) < _parse_version(candidate)


def _extract_current_version(file_path: Path, search_pattern: str) -> str | None:
    """Find the currently-pinned version in ``file_path`` using ``search_pattern``.

    Pulls a version-shaped substring out of each match so callers need not author
    named capture groups. Returns None when nothing matches.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        pattern_re = re.compile(search_pattern, flags=re.MULTILINE)
    except re.error:
        return None
    for match in pattern_re.finditer(content):
        version_match = _VERSION_RE.search(_GIT_SHA_RE.sub("", match.group(0)))
        if version_match:
            return version_match.group(0)
    return None


def _should_skip_due_to_downgrade(
    file_paths: list[Path], search_pattern: str, candidate: str
) -> bool:
    """True iff any file's current pin is already >= the candidate.

    Fails open — if no current version can be extracted, the replacement
    proceeds — so the gate never silently blocks a real update.
    """
    for file_path in file_paths:
        current = _extract_current_version(file_path, search_pattern)
        if current is None:
            continue
        if not _is_version_upgrade(current, candidate):
            log.info(
                f"--no-downgrade: {file_path} pins {current}, which is not older "
                f"than candidate {candidate}; leaving unchanged."
            )
            return True
    return False


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def _ensure_github_token() -> None:
    """Populate GITHUB_TOKEN from ``gh auth token`` when it isn't already set.

    CI injects the token. Locally the gh CLI usually holds one, and without it
    every request is unauthenticated and hits the 60/hour limit immediately.
    """
    if os.environ.get("GITHUB_TOKEN"):
        return

    gh_path = shutil.which("gh")
    if not gh_path:
        log.warning(
            "GITHUB_TOKEN not set and gh CLI not found; GitHub API calls will be unauthenticated"
        )
        return

    try:
        result = subprocess.run(
            [gh_path, "auth", "token"], capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError:
        log.warning("gh auth token failed; GitHub API calls will be unauthenticated")
        return

    token = result.stdout.strip()
    if token:
        os.environ["GITHUB_TOKEN"] = token
        log.info("Resolved GITHUB_TOKEN from gh CLI")


def _select_github_release(args, cooldown_days: int) -> str | None:
    """Newest GitHub release tag past its cooldown, or None if all are too recent."""
    source = f"{args.github_owner}/{args.github_repo}"
    releases = github.get_matching_releases(
        owner=args.github_owner,
        repo=args.github_repo,
        pin_level=args.pin_level,
        v_prefix=args.v_prefix,
    )
    if not releases:
        raise ValueError(
            f"No {args.pin_level}-level releases found for {source}"
        )
    log.info(
        f"Found {len(releases)} candidate release(s), newest: {releases[0]['tag_name']}"
    )

    for release in releases:
        version = release["tag_name"]
        published_at = github.parse_github_timestamp(release.get("published_at"))
        if not is_within_cooldown(published_at, cooldown_days, source=source):
            check_cooldown(
                published_at,
                cooldown_days,
                log,
                file_path=args.file[0],
                source_label=f"{source}@{version}",
                source=source,
            )
            return version
        elapsed = (datetime.now(timezone.utc) - published_at).days if published_at else 0
        log.debug(
            f"Skipping {version}: published {elapsed}d ago (cooldown: {cooldown_days}d)"
        )

    log.info(
        f"All {len(releases)} release(s) within cooldown ({cooldown_days}d). Skipping."
    )
    return None


def _select_docker_hub_tag(args, cooldown_days: int) -> str | None:
    """Newest Docker Hub tag past its cooldown, or None if all are too recent."""
    source = args.image
    candidates = docker_hub.get_matching_tags(
        repository=args.image,
        tag_template=args.tag_template,
        pin_level=args.pin_level,
        version_line=args.version_line,
        name_filter=args.tag_filter,
    )
    if not candidates:
        raise ValueError(
            f"No tags matching {args.tag_template!r} at {args.pin_level} level "
            f"found for image: {args.image}"
        )
    log.info(f"Found {len(candidates)} candidate tag(s), newest: {candidates[0].tag}")

    for candidate in candidates:
        if not is_within_cooldown(candidate.last_updated, cooldown_days, source=source):
            check_cooldown(
                candidate.last_updated,
                cooldown_days,
                log,
                file_path=args.file[0],
                source_label=f"{source}:{candidate.tag}",
                source=source,
            )
            return candidate.version
        elapsed = (
            (datetime.now(timezone.utc) - candidate.last_updated).days
            if candidate.last_updated
            else 0
        )
        log.debug(
            f"Skipping {candidate.tag}: pushed {elapsed}d ago (cooldown: {cooldown_days}d)"
        )

    log.info(
        f"All {len(candidates)} tag(s) within cooldown ({cooldown_days}d). Skipping."
    )
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update a pinned version in one or more files from an upstream source"
    )
    parser.add_argument(
        "--file",
        action="append",
        required=True,
        type=lambda p: Path(p).absolute(),
        help=(
            "File to update; repeatable. Several files sharing one pin are resolved "
            "with a single upstream lookup"
        ),
    )
    parser.add_argument(
        "--source-type",
        choices=["github-release", "docker-hub"],
        default="github-release",
        help="Where the upstream version comes from",
    )
    parser.add_argument("--github-owner", help="Required for --source-type github-release")
    parser.add_argument("--github-repo", help="Required for --source-type github-release")
    parser.add_argument(
        "--image",
        help="Docker Hub repository, e.g. 'library/python'. Required for --source-type docker-hub",
    )
    parser.add_argument(
        "--tag-template",
        default="{version}",
        help="Tag shape with a {version} placeholder, e.g. '{version}-slim' (docker-hub only)",
    )
    parser.add_argument(
        "--version-line",
        default="",
        help=(
            "Restrict to a release line, e.g. '1' or '3.13'. Use it when a major bump "
            "means a different artifact rather than a newer one (docker-hub only)"
        ),
    )
    parser.add_argument(
        "--tag-filter",
        default=None,
        help=(
            "Override the server-side tag substring filter. Defaults to the longest "
            "literal in --tag-template (docker-hub only)"
        ),
    )
    parser.add_argument(
        "--search-pattern",
        required=True,
        help="Regex matching the currently-pinned line",
    )
    parser.add_argument(
        "--replacement-pattern",
        required=True,
        help="Replacement text with a {version} placeholder",
    )
    parser.add_argument(
        "--pin-level",
        choices=["major", "minor", "patch"],
        default="patch",
        help="How many version segments the pin carries",
    )
    parser.add_argument(
        "--no-v-prefix",
        action="store_false",
        dest="v_prefix",
        default=True,
        help="The upstream version has no leading 'v'",
    )
    parser.add_argument(
        "--strip-v-in-replacement",
        action="store_true",
        default=False,
        help="Drop the 'v' prefix when writing to the file, even though the source has one",
    )
    parser.add_argument(
        "--cooldown-days",
        type=int,
        default=7,
        help=(
            "Minimum age in days of an upstream release before adopting it. "
            "Gives a supply chain compromise time to be detected first "
            "(https://github.com/aquasecurity/trivy/discussions/10425)"
        ),
    )
    parser.add_argument(
        "--no-downgrade",
        action="store_true",
        default=False,
        help="Skip the replacement when the pinned version is already >= the candidate",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LABS_LOGLEVEL", "INFO"),
        help="Python logging level",
    )

    args = parser.parse_args(argv)

    if args.source_type == "github-release":
        missing = [
            flag
            for flag, value in (
                ("--github-owner", args.github_owner),
                ("--github-repo", args.github_repo),
            )
            if not value
        ]
        if missing:
            parser.error(
                f"{', '.join(missing)} required when --source-type is github-release"
            )
    elif args.source_type == "docker-hub":
        if not args.image:
            parser.error("--image is required when --source-type is docker-hub")

    if "{version}" not in args.replacement_pattern:
        parser.error("--replacement-pattern must reference {version}")

    return args


def run(args: argparse.Namespace) -> None:
    file_paths: list[Path] = args.file

    missing = [str(p) for p in file_paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"These files do not exist: {', '.join(missing)}")

    if args.source_type == "github-release":
        _ensure_github_token()

    log.info(f"Fetching versions from {args.source_type}...")
    if args.source_type == "github-release":
        new_version = _select_github_release(args, args.cooldown_days)
    else:
        new_version = _select_docker_hub_tag(args, args.cooldown_days)

    if new_version is None:
        return

    log.info(f"Selected version: {new_version}")

    if args.no_downgrade and _should_skip_due_to_downgrade(
        file_paths, args.search_pattern, new_version
    ):
        return

    # Verify release integrity before writing anything: the tag must exist as a
    # ref in the repo it claims to come from, and the commit it resolves to must
    # be reachable from a branch there. An imposter commit pushed to a fork
    # satisfies neither.
    # https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23
    if args.source_type == "github-release":
        result = github.verify_tag_commit_integrity(
            owner=args.github_owner, repo=args.github_repo, tag=new_version
        )
        log.info(
            f"Verified: tag={new_version} commit={result['commit_sha']} "
            f"branch={result['reachable_from_branch'] or '(none; see warning)'}"
        )

    replacement_version = new_version
    if args.strip_v_in_replacement and replacement_version.startswith("v"):
        replacement_version = replacement_version[1:]
        log.info(
            f"Stripping 'v' prefix for replacement: {new_version} -> {replacement_version}"
        )

    replacement = args.replacement_pattern.format(version=replacement_version)

    for file_path in file_paths:
        contents = file_path.read_text(encoding="utf-8")
        updated, count = re.subn(
            args.search_pattern, replacement, contents, flags=re.MULTILINE
        )
        if count == 0:
            # A pin that stops matching is how an update silently becomes a
            # no-op, so this is loud rather than a debug line.
            log.warning(
                f"No matches for pattern '{args.search_pattern}' in {file_path}"
            )
            continue
        if updated == contents:
            log.info(f"{file_path} already pinned to {replacement_version}; no change")
            continue
        file_path.write_text(updated, encoding="utf-8")
        log.info(f"Updated {file_path} to {replacement_version} ({count} replacement(s))")


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s"
    )
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
