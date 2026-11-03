"""Copyright (c) 2026 Zenable, Inc. Forty-eight commit subject lines, and the Conventional Commits type of each.

The type vocabulary is arbitrary in the way most internal vocabularies are:
nothing in the words "chore" or "build" tells a model that a dependency bump is
one and a CI workflow edit is the other. That is the point. A small model can
read English perfectly well and still put a README change under `chore`,
because it has no way to know which convention this repository follows.

Nothing here is ambiguous to a person who knows the convention. Where two types
could argue over a line, the line names what it did to the code, so the label
follows the convention rather than the mood of whoever wrote the subject.
"""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

CommitType = Literal[
    "feat",
    "fix",
    "docs",
    "refactor",
    "test",
    "chore",
    "perf",
    "build",
]
"""The vocabulary, written once. The signature annotates its output field with
this type, so the adapter holds the model to it and nothing has to repeat the
list in a prompt."""

TYPES: tuple[str, ...] = get_args(CommitType)


class Commit(BaseModel):
    """One subject line, and the type a maintainer would give it."""

    model_config = ConfigDict(frozen=True, strict=True)

    subject: str
    commit_type: CommitType


COMMITS: tuple[Commit, ...] = (
    Commit(subject="add a retry budget to the payment client", commit_type="feat"),
    Commit(subject="support filtering findings by severity", commit_type="feat"),
    Commit(
        subject="allow an admin to revoke a session from the users page",
        commit_type="feat",
    ),
    Commit(
        subject="accept a webhook signature header on the import endpoint",
        commit_type="feat",
    ),
    Commit(subject="add a --dry-run flag to the migration runner", commit_type="feat"),
    Commit(subject="send a Slack message when a scan finishes", commit_type="feat"),
    Commit(subject="correct an off-by-one in the pagination cursor", commit_type="fix"),
    Commit(
        subject="stop the reaper deleting fleets it does not own", commit_type="fix"
    ),
    Commit(
        subject="handle a null tenant on the onboarding callback", commit_type="fix"
    ),
    Commit(
        subject="close the file handle when the upload is rejected", commit_type="fix"
    ),
    Commit(
        subject="return 404 rather than 500 for a deleted requirement",
        commit_type="fix",
    ),
    Commit(
        subject="escape the regex before compiling the user filter", commit_type="fix"
    ),
    Commit(
        subject="note the new environment variable in the README", commit_type="docs"
    ),
    Commit(
        subject="write up the on-call runbook for queue backlogs", commit_type="docs"
    ),
    Commit(subject="explain why the cache key includes the tenant", commit_type="docs"),
    Commit(subject="fix the broken link in the contributing guide", commit_type="docs"),
    Commit(subject="document the rate limits on the public API", commit_type="docs"),
    Commit(
        subject="add an architecture diagram to the design notes", commit_type="docs"
    ),
    Commit(
        subject="extract the retry helper into its own module", commit_type="refactor"
    ),
    Commit(
        subject="split the settings page into three components", commit_type="refactor"
    ),
    Commit(
        subject="replace the hand-rolled parser with the shared one",
        commit_type="refactor",
    ),
    Commit(
        subject="move the scope resolver next to its only caller",
        commit_type="refactor",
    ),
    Commit(
        subject="collapse the two nearly identical serialisers", commit_type="refactor"
    ),
    Commit(
        subject="rename tenant_uid to customer_uid across the repository",
        commit_type="refactor",
    ),
    Commit(
        subject="add a regression test for the partial refund path", commit_type="test"
    ),
    Commit(
        subject="cover the expired-token branch of the authoriser", commit_type="test"
    ),
    Commit(
        subject="assert the migration is idempotent when re-run", commit_type="test"
    ),
    Commit(
        subject="add fixtures for a tenant with no integrations", commit_type="test"
    ),
    Commit(
        subject="stop the flaky clock assertion in the scheduler suite",
        commit_type="test",
    ),
    Commit(
        subject="check that audit rows survive a failed transaction", commit_type="test"
    ),
    Commit(subject="bump actions/checkout to v5", commit_type="build"),
    Commit(subject="pin the Node version in the Dockerfile", commit_type="build"),
    Commit(subject="publish the CLI for windows/arm64 as well", commit_type="build"),
    Commit(subject="cache the uv download between workflow jobs", commit_type="build"),
    Commit(subject="drop Python 3.10 from the test matrix", commit_type="build"),
    Commit(
        subject="sign the release archives with the new certificate",
        commit_type="build",
    ),
    Commit(
        subject="index findings on (tenant_uid, created_at) to cut the scan",
        commit_type="perf",
    ),
    Commit(
        subject="batch the embedding calls instead of one per finding",
        commit_type="perf",
    ),
    Commit(
        subject="reuse the HTTPS client rather than rebuilding it per request",
        commit_type="perf",
    ),
    Commit(
        subject="stream the export instead of buffering the whole file",
        commit_type="perf",
    ),
    Commit(
        subject="skip the LLM call when the gate selects nothing", commit_type="perf"
    ),
    Commit(subject="memoise the scope lookup inside one request", commit_type="perf"),
    Commit(subject="delete the unused staging bucket module", commit_type="chore"),
    Commit(subject="rotate the expired signing key", commit_type="chore"),
    Commit(subject="add the new team to CODEOWNERS", commit_type="chore"),
    Commit(subject="raise the log level of the reaper to INFO", commit_type="chore"),
    Commit(
        subject="remove the feature flag for credit transitions", commit_type="chore"
    ),
    Commit(subject="archive last quarter's evidence bundle", commit_type="chore"),
)

# Six of each type, laid out in blocks above, so a contiguous slice would train
# on four types and test on two. Every third line goes to development and every
# third plus one to the held-out set, which leaves each split carrying every
# type.
DEVELOPMENT: tuple[Commit, ...] = COMMITS[0::3]
HELD_OUT: tuple[Commit, ...] = COMMITS[1::3]
TRAIN: tuple[Commit, ...] = COMMITS[2::3]
