"""Docker Hub tag discovery for image pins.

New code rather than a port. ``zenable_monorepo.registry`` resolves a pin by
asking which semver tag shares a digest with ``latest``, which cannot express
either of this repository's image pins: ``python:3.13-slim`` is a suffixed tag
that ``latest`` never points at, and ``jaegertracing/all-in-one`` must stay on
its 1.x line because 2.x moved to a different image entirely.

So a pin here is a *tag template* plus an optional version line, and discovery
is a filtered listing rather than a digest comparison.

Cooldown caveat, deliberately not hidden: ``last_updated`` is when the tag was
last PUSHED, not when the version first appeared, so it only means "this version
is N days old" for a tag the publisher writes once. That holds for a release tag
like ``jaegertracing/all-in-one:1.76.0`` and does NOT hold for a floating tag
like ``python:3.13-slim``, which is rebuilt whenever its base OS changes and is
therefore permanently a day old.

The failure is safe but useless: every candidate reads as too recent, so the pin
never moves. Do not use this source for a floating tag — take the version from a
source with a real publish date, or pin the digest. The timestamp is
registry-controlled either way, and so unforgeable by a committer, which is why
it is classified RELIABLE.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from supply_chain.github import sort_key
from supply_chain.retry import raising_session, retry_on_transient

log = logging.getLogger(__name__)

_LEVEL_SUFFIXES: dict[str, str] = {
    "major": r"\d+",
    "minor": r"\d+\.\d+",
    "patch": r"\d+\.\d+\.\d+",
}

_PAGE_SIZE = 100

# Docker Hub holds thousands of tags for a popular image. The cap keeps a
# misconfigured filter from paging forever; hitting it raises rather than
# returning a partial listing, because "newest of the first 30 pages" is a
# wrong answer that looks like a right one.
_MAX_PAGES = 30

_VERSION_PLACEHOLDER = "{version}"


@dataclass(frozen=True)
class TagInfo:
    """One Docker Hub tag that matched the pin's template."""

    version: str
    tag: str
    last_updated: datetime | None


def _version_regex(pin_level: str, version_line: str) -> str:
    """Build the version portion of the tag regex.

    ``version_line`` narrows to a release line ("1" or "3.13") and is matched
    literally; the remaining segments come from the pin level.
    """
    try:
        full = _LEVEL_SUFFIXES[pin_level]
    except KeyError:
        raise ValueError(f"Unsupported pin_level: {pin_level}") from None

    if not version_line:
        return full

    line_parts = version_line.split(".")
    level_parts = full.split(r"\.")
    if len(line_parts) > len(level_parts):
        raise ValueError(
            f"version_line {version_line!r} is more specific than pin_level "
            f"{pin_level!r}; it would match nothing"
        )
    for part in line_parts:
        if not part.isdigit():
            raise ValueError(f"version_line must be numeric segments, got: {version_line!r}")

    remaining = level_parts[len(line_parts) :]
    return r"\.".join([re.escape(p) for p in line_parts] + remaining)


def _tag_regex(tag_template: str, pin_level: str, version_line: str) -> re.Pattern[str]:
    """Compile the fully-anchored regex a candidate tag must match.

    Anchored for the same reason the GitHub tag pattern is: it is what keeps
    ``3.13.1-slim-bookworm`` from satisfying a ``{version}-slim`` minor pin.
    """
    if _VERSION_PLACEHOLDER not in tag_template:
        raise ValueError(f"tag_template must contain {_VERSION_PLACEHOLDER}: {tag_template!r}")
    prefix, _, suffix = tag_template.partition(_VERSION_PLACEHOLDER)
    version_part = _version_regex(pin_level, version_line)
    return re.compile(rf"^{re.escape(prefix)}({version_part}){re.escape(suffix)}$")


def default_tag_filter(tag_template: str, version_line: str) -> str:
    """Pick the Docker Hub ``name=`` substring that narrows the listing most.

    The API takes one substring filter, so choose the longest literal in the
    template — for ``{version}-slim`` that is ``-slim``, which cuts
    ``library/python`` from thousands of tags to hundreds. With no literal to
    use, fall back to the version line.
    """
    literals = [part for part in tag_template.split(_VERSION_PLACEHOLDER) if part]
    if literals:
        return max(literals, key=len)
    return f"{version_line}." if version_line else ""


@retry_on_transient(max_attempts=5)
def _get_page(session, url: str, params: dict | None) -> dict:
    return session.get(url, params=params, timeout=30).json()


def fetch_tags(repository: str, name_filter: str = "") -> list[dict]:
    """List a repository's tags, following pagination.

    :param repository: ``namespace/name``; a bare name is assumed to be official.
    :param name_filter: Substring the tag name must contain, applied server-side.
    :raises ValueError: If the listing exceeds :data:`_MAX_PAGES`.
    """
    if "/" not in repository:
        repository = f"library/{repository}"

    session = raising_session()
    url: str | None = f"https://hub.docker.com/v2/repositories/{repository}/tags"
    params: dict | None = {"page_size": _PAGE_SIZE, "name": name_filter}

    tags: list[dict] = []
    for _ in range(_MAX_PAGES):
        payload = _get_page(session, url, params)
        tags.extend(payload.get("results", []))
        url = payload.get("next")
        # The `next` link already carries the query string.
        params = None
        if not url:
            return tags

    raise ValueError(
        f"Tag listing for {repository} (name={name_filter!r}) exceeded {_MAX_PAGES} "
        f"pages. Narrow the filter rather than raising the cap: a truncated "
        f"listing silently yields the wrong 'newest' tag."
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse a Docker Hub ISO-8601 timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        log.warning("Unparseable Docker Hub timestamp: %s", value)
        return None


def get_matching_tags(
    repository: str,
    tag_template: str,
    pin_level: str = "minor",
    version_line: str = "",
    name_filter: str | None = None,
) -> list[TagInfo]:
    """Return the tags matching the template and pin level, newest-first.

    :param repository: Docker Hub repository, e.g. ``library/python``.
    :param tag_template: Tag shape with a ``{version}`` placeholder, e.g. ``{version}-slim``.
    :param pin_level: "major", "minor", or "patch" — how many version segments the tag carries.
    :param version_line: Restrict to a release line, e.g. ``1`` or ``3.13``.
    :param name_filter: Override the server-side substring filter.
    """
    matcher = _tag_regex(tag_template, pin_level, version_line)
    if name_filter is None:
        name_filter = default_tag_filter(tag_template, version_line)

    log.info(
        "Listing %s tags matching %s (name filter: %r)",
        repository,
        matcher.pattern,
        name_filter,
    )
    raw_tags = fetch_tags(repository, name_filter)

    matches: list[TagInfo] = []
    for entry in raw_tags:
        name = entry.get("name", "")
        matched = matcher.match(name)
        if not matched:
            continue
        matches.append(
            TagInfo(
                version=matched.group(1),
                tag=name,
                last_updated=_parse_timestamp(entry.get("last_updated")),
            )
        )

    matches.sort(key=lambda t: sort_key(t.version), reverse=True)
    return matches
