"""Supply-chain cooldown primitives shared across the update tooling.

Lags dependency adoption behind upstream releases by ``cooldown_days`` so there
is time for a supply chain compromise to be detected before we consume a new
release. See https://github.com/aquasecurity/trivy/discussions/10425

Timestamp reliability matters: some sources expose infrastructure-controlled
publish times (GitHub release ``published_at``, Docker Hub ``last_updated``)
that a committer cannot forge, while others only expose VCS commit or tag times
that are forgeable via ``GIT_COMMITTER_DATE``. Callers classify their source via
:class:`TimestampReliability` so the distinction surfaces in the run's
annotations rather than being invisibly assumed away.

Kept behaviourally identical to ``zenable_monorepo.cooldown`` in
Zenable-io/next-gen-governance so a fix there ports here as a readable diff.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from supply_chain import annotations


class TimestampReliability:
    """Classifies trustworthiness of timestamps used in security-sensitive checks.

    UNRELIABLE: git commit/author dates and tag dates — forgeable via
    GIT_COMMITTER_DATE, GIT_AUTHOR_DATE, or history rewrites.

    RELIABLE: registry publish times and GitHub API timestamps —
    infrastructure-controlled, not forgeable by a committer.
    """

    RELIABLE = "reliable"
    UNRELIABLE = "unreliable"


def emit_cooldown_annotation(
    file_path: Path,
    reliability: str,
    timestamp: str,
    elapsed_days: int,
    cooldown_days: int,
    allowed: bool,
) -> None:
    """Annotate which kind of timestamp a cooldown decision rested on.

    Surfaces on the run summary, so reliance on forgeable data is visible
    rather than buried in a log line nobody reads.
    """
    status = "allowed" if allowed else "blocked"

    if reliability == TimestampReliability.UNRELIABLE:
        annotations.warning(
            f"Cooldown check ({status}) used a forgeable timestamp ({timestamp}, "
            f"{elapsed_days}d ago, cooldown={cooldown_days}d). "
            f"VCS timestamps are forgeable via GIT_COMMITTER_DATE/GIT_AUTHOR_DATE. "
            f"Immutable sources (registry publish time) are preferred.",
            file=file_path,
            title=f"cooldown-timestamp-{reliability}",
        )
    else:
        annotations.notice(
            f"Cooldown check ({status}) used verified timestamp ({timestamp}, "
            f"{elapsed_days}d ago, cooldown={cooldown_days}d).",
            file=file_path,
            title=f"cooldown-timestamp-{reliability}",
        )


# The cooldown buys time for SOMEONE ELSE to notice a compromised upstream, so
# for a repo we publish ourselves it protects nothing and only blocks adopting
# something we just shipped. Waived centrally, never by a per-caller flag: one
# list to review, one place to audit.
#
# Keys are the upstream's stable identity, lowercased — never a versioned label,
# which would silently stop matching on the next release and quietly re-impose
# the cooldown nobody meant to restore.
COOLDOWN_EXEMPT_SOURCES: dict[str, str] = {
    "zenable-io/labs": "this repo; a release of ours is not third-party supply chain",
    "jonzeolla/lab-resources": "Zenable-owned; we cut the releases we consume",
}


def is_cooldown_exempt(source: str | None) -> bool:
    """True when ``source`` is centrally allowlisted out of the cooldown."""
    if not source:
        return False
    return source.strip().lower() in COOLDOWN_EXEMPT_SOURCES


def is_within_cooldown(
    published_at: datetime | None, cooldown_days: int, *, source: str | None = None
) -> bool:
    """Quick cooldown check without logging or annotations.

    Returns True if the version is too recent (still within the cooldown).
    """
    if is_cooldown_exempt(source):
        return False
    if cooldown_days <= 0:
        return False
    if published_at is None:
        return False
    return datetime.now(timezone.utc) - published_at < timedelta(days=cooldown_days)


def check_cooldown(
    published_at: datetime | None,
    cooldown_days: int,
    log,
    *,
    file_path: Path | None = None,
    source_label: str = "",
    source: str | None = None,
    reliability: str = TimestampReliability.RELIABLE,
) -> bool:
    """Check whether enough time has passed since the upstream release published.

    :param published_at: When the upstream version was published (None to skip).
    :param cooldown_days: Minimum age in days of a release before we adopt it.
    :param log: Logger instance.
    :param file_path: Optional file path for CI annotations.
    :param source_label: Human-readable label for logs (e.g. "keycloak/keycloak@26.7.2").
    :param source: Stable upstream identity checked against
        :data:`COOLDOWN_EXEMPT_SOURCES`. Omit to apply the cooldown unconditionally.
    :param reliability: Whether the timestamp source is forgeable.
    :return: True if the cooldown has elapsed (OK to update), False otherwise.
    """
    if is_cooldown_exempt(source):
        # Annotated, not merely logged: waiving a supply-chain control should be
        # visible on the run that did it.
        assert source is not None
        msg = (
            f"Cooldown waived for {source}: "
            f"{COOLDOWN_EXEMPT_SOURCES[source.strip().lower()]}"
        )
        log.info(msg)
        annotations.notice(msg, file=file_path, title="cooldown-exempt-source")
        return True

    if cooldown_days <= 0:
        return True

    if published_at is None:
        msg = (
            "No publish date available for upstream release, skipping cooldown check. "
            "Cooldown provides no protection for this source."
        )
        log.warning(msg)
        annotations.warning(
            msg, file=file_path, title="cooldown-bypassed-no-publish-date"
        )
        return True

    elapsed = datetime.now(timezone.utc) - published_at
    allowed = elapsed >= timedelta(days=cooldown_days)

    emit_cooldown_annotation(
        file_path=file_path or Path("unknown"),
        reliability=reliability,
        timestamp=published_at.isoformat(),
        elapsed_days=elapsed.days,
        cooldown_days=cooldown_days,
        allowed=allowed,
    )

    if not allowed:
        label = f" ({source_label})" if source_label else ""
        log.info(
            f"Cooldown active: upstream release{label} published {elapsed.days}d ago "
            f"(cooldown: {cooldown_days}d). Skipping."
        )
        return False

    return True
