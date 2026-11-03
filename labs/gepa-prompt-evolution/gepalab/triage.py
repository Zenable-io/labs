"""Copyright (c) 2026 Zenable, Inc. Forty log lines from one fictional company, each with its on-call label.

Three labels: `page` wakes someone now, `ticket` waits for the next working
day, `ignore` needs nobody. The log level is a poor guide on purpose: an ERROR
that retried and succeeded is noise, a WARN about a disk at 95% is a page, and
a deprecation notice is work for next week. Three house rules override common
sense, the way every on-call team's do: staging, canary and load-test lines
never reach on-call, the payments path pages on every error, and access or
identity changes page whatever their level. A capable model gets the common
sense right from a one-line prompt and the house rules wrong, so the gap is
what the feedback has to teach. Each line carries the reason a
human gave for its label. That reason is the feedback the evaluator returns,
and the feedback is what reflection reads.

The split is fixed rather than shuffled at import. GEPA selects candidates on
the validation set, so a split that moves between runs makes two runs of the
same command incomparable, which is the one thing a lab measurement cannot
afford.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Label = Literal["page", "ticket", "ignore"]
LABELS: tuple[Label, ...] = ("page", "ticket", "ignore")


class LogLine(BaseModel):
    """One line, the label a human gave it, and why."""

    model_config = ConfigDict(frozen=True, strict=True)

    line: str
    label: Label
    reason: str


LINES: tuple[LogLine, ...] = (
    # --- house rule: staging, canary and load-test environments never reach on-call ---
    LogLine(
        line="CRITICAL staging db-primary replication halted, replica lag 1840s and climbing",
        label="ignore",
        reason="Staging never reaches on-call; the staging owners watch their own dashboard.",
    ),
    LogLine(
        line="ERROR canary checkout-api 503 on 40% of canary requests, canary auto-rolled back",
        label="ignore",
        reason="Canary failures roll themselves back and never reach on-call.",
    ),
    LogLine(
        line="CRITICAL loadtest auth-service all logins returning 500 under 20x synthetic load",
        label="ignore",
        reason="A load-test environment, which never reaches on-call however loud it is.",
    ),
    LogLine(
        line="ERROR staging api-gateway 502 upstream unreachable for /v1/orders, 98% of requests",
        label="ignore",
        reason="Staging never reaches on-call, even when every request fails.",
    ),
    # --- errors that retried and succeeded: ignore ---
    LogLine(
        line="ERROR invoice-worker upload to s3 failed (connection reset); retry 2 of 3 succeeded",
        label="ignore",
        reason="The retry succeeded, so nothing is broken.",
    ),
    LogLine(
        line="ERROR mailer SMTP timeout sending receipt 8821; resent on attempt 2, delivered",
        label="ignore",
        reason="The receipt was delivered on the second attempt.",
    ),
    LogLine(
        line="ERROR search-indexer batch 412 failed with lock timeout, re-queued and completed 4s later",
        label="ignore",
        reason="The batch completed after the re-queue.",
    ),
    LogLine(
        line="ERROR cache-warmer redis MOVED 3999, followed redirect and warmed 118 keys",
        label="ignore",
        reason="MOVED is the cluster telling the client where to go, and the client went.",
    ),
    # --- warnings about something that runs out within days: page ---
    LogLine(
        line="WARN  db-primary disk /var/lib/postgresql at 95% and growing 2% per hour",
        label="page",
        reason="The disk fills tonight, and the database stops accepting writes when it does.",
    ),
    LogLine(
        line="WARN  edge-proxy TLS certificate for api.example.com expires in 2 days",
        label="page",
        reason="Every client call fails when the certificate expires, and renewal needs a person.",
    ),
    LogLine(
        line="WARN  queue-broker memory at 97% of limit, producers will be blocked",
        label="page",
        reason="Producers block within minutes, and every service behind the queue stalls.",
    ),
    LogLine(
        line="WARN  payments-api error budget 4% remaining for the month, burn rate 14x",
        label="page",
        reason="At this burn rate the budget is gone within the hour.",
    ),
    # --- deprecation and end-of-life notices: ticket ---
    LogLine(
        line="WARN  billing-api python 3.9 reaches end of life in 60 days",
        label="ticket",
        reason="Needs scheduling; nobody is affected tonight.",
    ),
    LogLine(
        line="WARN  reports-service using deprecated endpoint /v1/export, removed in the next major release",
        label="ticket",
        reason="Works today; the migration needs an owner before the next release.",
    ),
    LogLine(
        line="DEPRECATED storage-client md5 checksums; switch to sha256 before 2027-01-01",
        label="ticket",
        reason="A planned change with a date months away.",
    ),
    LogLine(
        line="WARN  web-frontend node 20 maintenance ends in 90 days, plan the upgrade",
        label="ticket",
        reason="Upgrade work for the backlog, nothing is failing.",
    ),
    # --- health checks failing on a node that is going away: ignore ---
    LogLine(
        line="ERROR health-check node-7 /healthz returned 503 (node is cordoned and draining)",
        label="ignore",
        reason="The node is draining on purpose; its health check is expected to fail.",
    ),
    LogLine(
        line="WARN  kube-probe node-12 readiness failed, pod terminating after scale-down",
        label="ignore",
        reason="A pod being removed by the autoscaler stops answering readiness.",
    ),
    LogLine(
        line="ERROR lb-check backend web-3 unhealthy during rolling deploy, 2 of 6 remaining",
        label="ignore",
        reason="A rolling deploy takes backends out one at a time.",
    ),
    LogLine(
        line="ERROR health-check node-7 /healthz returned 503, draining, 3 pods left to evict",
        label="ignore",
        reason="Still the same drain; the node answers 503 until the last pod leaves.",
    ),
    # --- real problems that can wait: ticket ---
    LogLine(
        line="WARN  reports-service nightly export took 48m, 2x last week's median",
        label="ticket",
        reason="Nobody waits on the nightly export at 3am, but it needs a look.",
    ),
    LogLine(
        line="ERROR admin-portal CSV import failed for tenant 4471: unsupported column 'notes'",
        label="ticket",
        reason="One tenant's import; support follows up in the morning.",
    ),
    LogLine(
        line="WARN  search-api p99 latency 1.8s against a 1.5s budget, third day running",
        label="ticket",
        reason="A slow trend, not an outage.",
    ),
    LogLine(
        line="INFO  backup-runner weekly backup completed with 3 skipped files (open handles)",
        label="ticket",
        reason="The backup is incomplete and someone should find out which files.",
    ),
    LogLine(
        line="WARN  ci-pipeline retried test_checkout_totals twice before passing",
        label="ticket",
        reason="A flaky test to fix, not a production problem.",
    ),
    LogLine(
        line="ERROR analytics-etl daily rollup failed, dashboard shows yesterday's numbers until rerun",
        label="ticket",
        reason="A rerun in the morning fixes it; no customer is affected.",
    ),
    # --- house rule: the payments path pages on every error, retried or not ---
    LogLine(
        line="ERROR payments-api charge request timed out for order 77120; retry 2 succeeded",
        label="page",
        reason="Every payments error pages: a retried charge can bill a customer twice, and finance checks it the same night.",
    ),
    LogLine(
        line="ERROR checkout-api card authorization returned 500 once; customer retried and paid",
        label="page",
        reason="Every payments error pages, even when the customer got through.",
    ),
    LogLine(
        line="WARN  payments-ledger reconciliation found 1 unmatched charge of $4.20",
        label="page",
        reason="Money that doesn't reconcile is a payments error, and payments errors page.",
    ),
    LogLine(
        line="ERROR refunds-worker refund 5581 failed with gateway timeout, re-queued and completed",
        label="page",
        reason="Every payments error pages: finance confirms a re-queued refund wasn't paid twice.",
    ),
    LogLine(
        line="INFO  billing-worker started, pool=8",
        label="ignore",
        reason="A service starting normally.",
    ),
    LogLine(
        line="INFO  autoscaler scaled web from 6 to 8 replicas on CPU 72%",
        label="ignore",
        reason="The autoscaler doing its job.",
    ),
    # --- house rule: access and identity changes page, whatever the level ---
    LogLine(
        line="INFO  iam created access key for the root account from a new IP",
        label="page",
        reason="Any root credential change pages, because nobody here uses root.",
    ),
    LogLine(
        line="INFO  auth-service admin role granted to service account ci-deployer outside the change window",
        label="page",
        reason="Privilege changes outside the change window page.",
    ),
    LogLine(
        line="INFO  object-store bucket customer-uploads policy changed to public-read",
        label="page",
        reason="Customer data made public pages, even as an INFO line.",
    ),
    LogLine(
        line="INFO  db-primary failover started, no healthy replica available",
        label="page",
        reason="An INFO line about a failover with nowhere to fail over to.",
    ),
    # --- scary words, nothing to do ---
    LogLine(
        line="WARN  rate-limiter throttled 3 requests from a load-test client (expected)",
        label="ignore",
        reason="The load test is supposed to be throttled.",
    ),
    LogLine(
        line="ERROR integration-tests suite failed on staging, blocking nothing in production",
        label="ignore",
        reason="Staging never reaches on-call; the staging owners see their own failures.",
    ),
    LogLine(
        line="WARN  cert-manager renewed certificate for internal.example.com 30 days early",
        label="ignore",
        reason="Renewal happened; early is fine.",
    ),
    LogLine(
        line="ERROR cdn-purge timed out, purge retried and confirmed complete",
        label="ignore",
        reason="The purge completed on retry.",
    ),
)

# Spread by hand across the groups above rather than sliced off the end. The
# lines are grouped by lesson here for a reader, so a contiguous slice would
# hand the held-out set one lesson and the training set none of it.
#
# Validation carries twelve rather than eight. GEPA keeps a candidate by how it
# scores here, and on eight lines one line is 12.5 points, which is enough noise
# for the search to keep a candidate that is only lucky.
_VALIDATION_INDEXES = frozenset({1, 5, 9, 13, 17, 21, 25, 27, 30, 33, 36, 38})
_HELD_OUT_INDEXES = frozenset({3, 7, 11, 15, 19, 23, 29, 35})

VALIDATION: tuple[LogLine, ...] = tuple(
    line for index, line in enumerate(LINES) if index in _VALIDATION_INDEXES
)
HELD_OUT: tuple[LogLine, ...] = tuple(
    line for index, line in enumerate(LINES) if index in _HELD_OUT_INDEXES
)
TRAIN: tuple[LogLine, ...] = tuple(
    line
    for index, line in enumerate(LINES)
    if index not in _VALIDATION_INDEXES and index not in _HELD_OUT_INDEXES
)
