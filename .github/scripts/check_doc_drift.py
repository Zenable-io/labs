#!/usr/bin/env python3
"""Report documentation that quotes a superseded image version.

Every lab's README carries recorded terminal output, and `evidence/` holds the
captured runs behind it. Both name image versions. When the automation bumps a
pin, that recorded output becomes wrong.

It is not fixed by a regex. A transcript rewritten to name a version nobody ran
is fabricated evidence, and the column alignment of `docker compose ps` output
would not survive the edit anyway. So this reports the drift and leaves the
files alone: a human regenerates them by running the lab, which is the same
thing that produced them in the first place.

Two different homes, which is why the report says which one applies. `evidence/`
belongs to this repository and comes from each lab's `scripts/capture-evidence.sh`.
Every `README.md` under `labs/` is GENERATED from that lab's `.mdx` in
Zenable-io/next-gen-governance and carries a "Do not edit by hand" banner saying
so — a fix committed here is silently reverted by the next export.

Config files are the source of truth. Anything found in a `.md` or under
`evidence/` naming a different version for the same image is reported.
"""

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from supply_chain import annotations

# `image: repo:tag` in compose, and `FROM repo:tag` in a Dockerfile. The tag is
# captured separately so a digest suffix or a trailing comment does not join it.
_IMAGE_RE = re.compile(
    r"(?:image:\s*|FROM\s+)(?P<repo>[a-z0-9][a-z0-9._/-]*[a-z0-9]):(?P<tag>[\w][\w.-]*)",
    re.IGNORECASE,
)

# The same reference as it appears in prose or recorded output, where it is not
# introduced by an `image:` or `FROM` key.
_MENTION_RE = re.compile(r"(?P<repo>[a-z0-9][a-z0-9._/-]*[a-z0-9]):(?P<tag>[\w][\w.-]*)")

# Recorded output often names a product rather than an image: `kc.sh --version`
# prints `Keycloak 26.7.1`, with no registry path and no colon, which the
# reference pattern above cannot see. Matched against the repository's last path
# segment, so `quay.io/keycloak/keycloak` also covers "Keycloak <version>".
_PRODUCT_RE_TEMPLATE = r"\b{name}[ :v]+(?P<tag>\d+\.\d+(?:\.\d+)*)\b"

# Only plain-semver pins take part in the product-name check. A templated tag
# like python's `3.13-slim` has no clean version to compare against, and the
# labs legitimately print a fuller `Python 3.13.12` for the same pin — which
# would read as drift on every single run.
_PLAIN_VERSION_RE = re.compile(r"^v?\d+\.\d+(?:\.\d+)*$")

# `*Dockerfile*` rather than `*Dockerfile`, because a lab that builds more than
# one image suffixes them — `Dockerfile.get-started`, `Dockerfile.tickets`. The
# unsuffixed glob silently skipped both, which reads as "no drift" rather than
# as an error.
_CONFIG_GLOBS = ("*compose.yml", "*compose.yaml", "*Dockerfile*")
_DOC_GLOBS = ("*.md", "*.txt", "*.json")


def _tracked_files(root: Path, globs: tuple[str, ...]) -> list[Path]:
    """Git-tracked files matching any of ``globs``.

    Uses the index rather than a filesystem walk so a stray `.venv/` or a
    build artifact can never be mistaken for repository content.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", *globs],
        capture_output=True,
        text=True,
        check=True,
    )
    return [root / name for name in result.stdout.split("\0") if name]


def collect_pinned_versions(root: Path) -> dict[str, dict[str, set[Path]]]:
    """Map each image repository to the tags the config files pin it at.

    :return: ``{repo: {tag: {file, ...}}}``
    """
    pins: dict[str, dict[str, set[Path]]] = defaultdict(lambda: defaultdict(set))
    for path in _tracked_files(root, _CONFIG_GLOBS):
        for match in _IMAGE_RE.finditer(path.read_text(encoding="utf-8")):
            pins[match["repo"]][match["tag"]].add(path)
    return pins


def find_drift(root: Path, pins: dict[str, dict[str, set[Path]]]) -> list[str]:
    """Find documentation naming a tag the config files no longer use."""
    findings: list[str] = []
    config_files = {p.resolve() for p in _tracked_files(root, _CONFIG_GLOBS)}

    for path in _tracked_files(root, _DOC_GLOBS):
        if path.resolve() in config_files:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        seen: set[tuple[str, str]] = set()

        def record(repo: str, tag: str, shown: str, *, strip_v: bool = False) -> None:
            known_tags = pins.get(repo)
            # A bare `word:word` is far too common in prose to treat as an image
            # reference, so only repositories the config files actually pin count.
            if not known_tags:
                return
            # The product-name form captures the digits only, so `agentgateway:v1.4.1`
            # reaches here as `1.4.1` and would otherwise read as drift against its
            # own pin. The reference form keeps the tag verbatim, where a stray `v`
            # really is a different tag.
            comparable = (
                {t.lstrip("vV") for t in known_tags} if strip_v else known_tags
            )
            if (tag.lstrip("vV") if strip_v else tag) in comparable:
                return
            if (repo, tag) in seen:
                return
            seen.add((repo, tag))
            current = ", ".join(sorted(known_tags))
            findings.append(
                f"{path.relative_to(root)}: names {shown}, but the "
                f"configuration now pins {repo}:{current}"
            )

        for match in _MENTION_RE.finditer(content):
            record(match["repo"], match["tag"], f"{match['repo']}:{match['tag']}")

        for repo, known_tags in pins.items():
            if not any(_PLAIN_VERSION_RE.match(t) for t in known_tags):
                continue
            product = repo.rsplit("/", 1)[-1]
            product_re = re.compile(
                _PRODUCT_RE_TEMPLATE.format(name=re.escape(product)), re.IGNORECASE
            )
            for match in product_re.finditer(content):
                record(repo, match["tag"], f"{product} {match['tag']}", strip_v=True)

    return findings


def main() -> int:
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    findings = find_drift(root, collect_pinned_versions(root))
    if not findings:
        print("No documentation drift found.")
        return 0

    print(f"{len(findings)} file reference(s) now disagree with the pinned versions:")
    for finding in findings:
        print(f"  - {finding}")
        annotations.warning(finding, title="doc-quotes-superseded-version")

    print(
        "\nRegenerate the recorded output rather than editing it by hand. Where it "
        "lives depends on the file:\n"
        "  evidence/**  is owned here — re-run the lab's scripts/capture-evidence.sh.\n"
        "  README.md    is GENERATED from the lab's .mdx in Zenable-io/next-gen-governance\n"
        "               (services/ui_frontend/src/lib/labs/content/labs/). Fix the transcript\n"
        "               there, then re-export with\n"
        "               `node services/ui_frontend/scripts/export-lab-readme.js --all <this repo>`.\n"
        "               Editing README.md here is undone by the next export."
    )
    # Advisory, not a gate. The update PR should still open; a human decides
    # whether the transcripts are worth re-recording this week.
    return 0


if __name__ == "__main__":
    sys.exit(main())
