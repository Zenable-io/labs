"""GitHub release discovery and tag->commit integrity verification.

Trimmed from ``zenable_monorepo.github``: this repository has no monorepo tag
namespaces and no releaseless repositories to pin, so ``tag_namespace`` and the
git-refs tag source are omitted. The verification chain is carried over
unchanged — it is the part that matters.
"""

import functools
import logging
import os
import re
from datetime import datetime, timezone

import requests

from supply_chain import annotations
from supply_chain.retry import is_transient, raising_session, retry_on_transient

log = logging.getLogger(__name__)

_LEVEL_SUFFIXES: dict[str, str] = {
    "major": r"\d+",
    "minor": r"\d+\.\d+",
    "patch": r"\d+\.\d+\.\d+",
}


@functools.lru_cache(maxsize=None)
def version_pattern(v_prefix: bool = True, pin_level: str = "minor") -> re.Pattern[str]:
    """Compile the fully-anchored tag pattern for a pin level.

    The anchoring is load-bearing, not cosmetic. Upstreams mislabel prereleases:
    agentgateway ships ``v1.4.0-beta.1`` with ``prerelease: false``, so the
    release metadata alone would let a beta through. ``^v\\d+\\.\\d+\\.\\d+$``
    rejects it on shape regardless of what the publisher claimed.

    :param v_prefix: Whether the tag carries a leading ``v``.
    :param pin_level: "major", "minor", or "patch".
    """
    try:
        suffix = _LEVEL_SUFFIXES[pin_level]
    except KeyError:
        raise ValueError(f"Unsupported pin_level: {pin_level}") from None
    return re.compile(rf"^{'v' if v_prefix else ''}{suffix}$")


def sort_key(version: str) -> list:
    """Sort a version string numerically per segment, ignoring any ``v`` prefix."""
    return [
        int(part) if part.isdigit() else part
        for part in version.lstrip("vV").split(".")
    ]


def _github_headers() -> dict[str, str]:
    """Build GitHub API headers, including the auth token when one is available."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_github_timestamp(value: str | None) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp into an aware UTC datetime."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@retry_on_transient(max_attempts=5)
def get_matching_releases(
    owner: str,
    repo: str,
    pin_level: str = "minor",
    v_prefix: bool = True,
) -> list[dict]:
    """Return the releases whose tags match ``pin_level``, newest-first.

    Drafts and anything flagged ``prerelease`` are dropped, and the tag pattern
    then drops anything that merely looks like a prerelease. Each element is the
    full release dict, so the caller gets ``published_at`` without a second call.
    """
    tag_matcher = version_pattern(v_prefix, pin_level)

    releases_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    session = raising_session()
    response = session.get(releases_url, headers=_github_headers(), timeout=30)

    matching = []
    for release in response.json():
        if release.get("prerelease", False) or release.get("draft", False):
            continue
        if tag_matcher.match(release.get("tag_name", "")):
            matching.append(release)

    matching.sort(key=lambda r: sort_key(r["tag_name"]), reverse=True)
    return matching


@retry_on_transient(max_attempts=5)
def _get_tag_ref(owner: str, repo: str, tag: str) -> dict:
    """Get a tag reference from the repository's git refs.

    Confirms the tag exists as a first-class ref in THIS repo, rather than being
    merely reachable by SHA through GitHub's shared object storage, which
    includes every fork's objects.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag}"
    session = raising_session()
    response = session.get(url, headers=_github_headers(), timeout=30)
    return response.json()


@retry_on_transient(max_attempts=5)
def _resolve_ref_to_commit(owner: str, repo: str, ref_data: dict) -> str:
    """Resolve a git ref object to its underlying commit SHA.

    Handles both lightweight tags (type "commit") and annotated tags (type
    "tag"), which need a further dereference.
    """
    obj = ref_data["object"]
    if obj["type"] == "commit":
        return obj["sha"]
    if obj["type"] == "tag":
        url = f"https://api.github.com/repos/{owner}/{repo}/git/tags/{obj['sha']}"
        session = raising_session()
        response = session.get(url, headers=_github_headers(), timeout=30)
        tag_obj = response.json()
        if tag_obj["object"]["type"] != "commit":
            raise ValueError(
                f"Annotated tag dereferences to unexpected type: {tag_obj['object']['type']}"
            )
        return tag_obj["object"]["sha"]
    raise ValueError(f"Unexpected ref object type: {obj['type']}")


@retry_on_transient(max_attempts=5)
def _is_ancestor_of_branch(
    session: requests.Session, owner: str, repo: str, commit_sha: str, branch_name: str
) -> bool:
    """Check whether ``commit_sha`` is an ancestor of (or equal to) the branch.

    Uses the compare API: when the merge base of (commit, branch) equals the
    commit itself, the commit is in that branch's history.
    """
    compare_url = (
        f"https://api.github.com/repos/{owner}/{repo}/compare/{commit_sha}...{branch_name}"
    )
    try:
        response = session.get(compare_url, headers=_github_headers(), timeout=30)
        response.raise_for_status()
        merge_base_sha = response.json().get("merge_base_commit", {}).get("sha", "")
        return merge_base_sha == commit_sha
    except requests.HTTPError as exc:
        if is_transient(exc):
            raise
        # Debug, not warning: the caller walks every branch, so one line per
        # branch would bury the single verdict that matters under sixty copies
        # of it. An outright missing commit is caught by _commit_exists before
        # the walk starts, and the walk's own failure is annotated by the caller.
        log.debug(
            "Ancestry check for %s on %s/%s branch %s failed: %s",
            commit_sha,
            owner,
            repo,
            branch_name,
            exc,
        )
        return False


@retry_on_transient(max_attempts=5)
def _commit_exists(owner: str, repo: str, commit_sha: str) -> bool:
    """Whether ``commit_sha`` resolves at all under ``owner/repo``.

    Note this is NOT a provenance check and cannot replace reachability: because
    GitHub serves forks from shared object storage, a commit pushed only to a
    fork still resolves under the parent. It exists to fail a nonexistent SHA in
    one request instead of one per branch.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}"
    response = requests.get(url, headers=_github_headers(), timeout=30)
    # 404 is the ordinary "no such commit". 422 is what GitHub returns for a
    # SHA it will not even look up (the all-zero SHA, for one); both mean the
    # ref does not resolve here, and neither is worth a stack trace.
    if response.status_code in (404, 422):
        return False
    response.raise_for_status()
    return True


@retry_on_transient(max_attempts=5)
def _get_default_branch(owner: str, repo: str) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}"
    session = raising_session()
    response = session.get(url, headers=_github_headers(), timeout=30)
    return response.json().get("default_branch", "main")


@retry_on_transient(max_attempts=5)
def _get_branches(owner: str, repo: str, per_page: int = 100) -> list[dict]:
    """Get all branches for a repository, following pagination."""
    branches: list[dict] = []
    url: str | None = (
        f"https://api.github.com/repos/{owner}/{repo}/branches?per_page={per_page}"
    )
    session = raising_session()
    headers = _github_headers()
    while url:
        response = session.get(url, headers=headers, timeout=30)
        branches.extend(response.json())
        url = response.links.get("next", {}).get("url")
    return branches


def verify_commit_on_branch(owner: str, repo: str, commit_sha: str) -> str:
    """Verify a commit is reachable from at least one branch in the repository.

    Imposter commits — pushed to a fork but referenced by SHA as if they belonged
    to the parent repo — are not reachable from any branch of the parent. This is
    the core defense against:
    - https://github.com/aquasecurity/trivy/discussions/10425
    - https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23

    :return: The name of a branch the commit is reachable from.
    :raises ValueError: If the commit is unreachable (a potential imposter).
    """
    if not _commit_exists(owner, repo, commit_sha):
        raise ValueError(f"Commit {commit_sha} does not exist in {owner}/{repo}")

    session = requests.Session()

    # Check the default branch first; it is the overwhelmingly common case and
    # usually saves listing every branch.
    default_branch = _get_default_branch(owner, repo)
    if _is_ancestor_of_branch(session, owner, repo, commit_sha, default_branch):
        return default_branch

    # Fall back to every branch, which is what covers release branches.
    for branch in _get_branches(owner, repo):
        branch_name = branch["name"]
        if branch_name == default_branch:
            continue
        if _is_ancestor_of_branch(session, owner, repo, commit_sha, branch_name):
            return branch_name

    raise ValueError(
        f"Commit {commit_sha} is not reachable from any branch in {owner}/{repo}. "
        f"This may indicate an imposter commit from a fork. "
        f"See https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23"
    )


def verify_tag_commit_integrity(owner: str, repo: str, tag: str) -> dict:
    """Verify that a tag maps to a legitimate commit on the repository.

    1. Confirm the tag exists as a ref in this repo's git refs
    2. Resolve the tag to its underlying commit SHA (handling annotated tags)
    3. Corroborate by checking the commit is reachable from a named branch

    Step 1 is the load-bearing one, and it is a hard failure. Git refs are
    repo-scoped: a fork's tags never appear in the parent's refs, however freely
    GitHub's content-addressable storage shares the underlying objects. A tag ref
    present here was therefore created by someone with push access to this
    repository, which is exactly what the imposter-commit attack lacks — that
    attack references a *bare SHA* with no ref behind it.

    Step 3 is advisory here, and that is a deliberate difference from
    ``verify_action_pins.py``, where a bare SHA is all there is and reachability
    is the only defense available. Release tooling routinely tags a commit that
    never lands on a branch: Keycloak's ``Set version to 26.7.2`` is tagged and
    then superseded on ``release/26.7`` by the next development-version commit,
    so the tag commit legitimately diverges from every branch. Failing on that
    would block a correctly-published release, so it warns instead.

    :return: Dict with tag_ref_sha, commit_sha, and reachable_from_branch
        (``None`` when no branch reaches the commit).
    :raises ValueError: If the tag ref is missing or does not resolve to a commit.
    """
    log.info(f"Verifying tag integrity: {owner}/{repo}@{tag}")

    tag_ref = _get_tag_ref(owner, repo, tag)
    tag_ref_sha = tag_ref["object"]["sha"]
    log.info(
        f"Tag ref confirmed: {tag} -> {tag_ref_sha} (type: {tag_ref['object']['type']})"
    )

    commit_sha = _resolve_ref_to_commit(owner, repo, tag_ref)
    log.info(f"Resolved to commit: {commit_sha}")

    try:
        branch = verify_commit_on_branch(owner, repo, commit_sha)
    except ValueError:
        branch = None
        msg = (
            f"{owner}/{repo}@{tag} resolves to {commit_sha}, which is not reachable "
            f"from any branch. The tag ref itself is present in {owner}/{repo}, so "
            f"this is most likely a release-tooling commit that was tagged without "
            f"being merged back — but confirm the tag before merging."
        )
        log.warning(msg)
        annotations.warning(msg, title="tag-commit-not-on-branch")
    else:
        log.info(f"Commit {commit_sha} verified reachable from branch: {branch}")

    return {
        "tag_ref_sha": tag_ref_sha,
        "commit_sha": commit_sha,
        "reachable_from_branch": branch,
    }
