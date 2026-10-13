"""Copyright (c) 2026 Zenable, Inc. A stand-in for a week of coding-assistant traffic.

Twenty-two families of work, three ways of asking for each. The families carry a
label written before any Jev call, so the measurement grades the cache against
Jev rather than against itself.

Nothing on the surface of a message tracks which kind it is. Short questions
that need deciding sit beside long requests that do not, and the same opening
verb turns up on both. That is how real traffic reads, and it is what makes the
feature bucket in `features.py` worth measuring rather than assuming.

This corpus is made up. Real traffic repeats more than this and phrases itself
worse, so read these numbers as the shape of the answer and run the same
measurement over your own log before trusting one.
"""

import random

from pydantic import BaseModel, ConfigDict


class Family(BaseModel):
    """One unit of work, and three ways a person asks for it."""

    model_config = ConfigDict(frozen=True, strict=True)

    name: str
    kind: str
    """`mechanical` or `deliberative`, decided by hand before any Jev call."""

    forms: tuple[str, str, str]


FAMILIES: tuple[Family, ...] = (
    Family(
        name="rename-symbol",
        kind="mechanical",
        forms=(
            "Rename the variable `cfg` to `config` in src/app.py and update the two call sites.",
            "In src/app.py, `cfg` should be called `config`. Change it everywhere it appears.",
            "Please rename cfg -> config across src/app.py, including the callers in main().",
        ),
    ),
    Family(
        name="json-to-yaml",
        kind="mechanical",
        forms=(
            "Convert this JSON block to YAML, keeping the key order.",
            "Turn the attached JSON config into equivalent YAML.",
            "I need the same settings as YAML instead of JSON. Key order matters.",
        ),
    ),
    Family(
        name="add-type-hints",
        kind="mechanical",
        forms=(
            "Add type hints to every function in billing/refunds.py, including the "
            "return types, and use the built-in generics rather than the ones from "
            "typing.",
            "Annotate the parameters and return types in billing/refunds.py.",
            "billing/refunds.py has no annotations. Add them.",
        ),
    ),
    Family(
        name="extract-endpoints",
        kind="mechanical",
        forms=(
            "List every route path declared in this router file.",
            "Which endpoints does this file register? Just the paths.",
            "Pull out the URL paths from the decorators below.",
        ),
    ),
    Family(
        name="bash-to-make",
        kind="mechanical",
        forms=(
            "Rewrite this shell script as a Makefile with one target per step.",
            "Convert the build script below into make targets.",
            "Same steps, but as a Makefile instead of a bash script.",
        ),
    ),
    Family(
        name="comment-block",
        kind="mechanical",
        forms=(
            "Write a docstring for the function below describing its arguments, its "
            "return value and the exception it raises, in the same style as the "
            "other functions in the file.",
            "Add a docstring to this function. Arguments and return value.",
            "This function has no docstring. Write one from what it does.",
        ),
    ),
    Family(
        name="csv-header",
        kind="mechanical",
        forms=(
            "What are the column names in the first line of this CSV?",
            "Read the header row off this CSV and list the fields.",
            "Which columns does this export have? The header is on line one.",
        ),
    ),
    Family(
        name="regex-escape",
        kind="mechanical",
        forms=(
            "Escape this string so it can be used as a literal in a Python regex.",
            "Make the text below safe to drop into re.compile as a literal.",
            "Regex-escape this pattern, it has dots and brackets in it.",
        ),
    ),
    Family(
        name="translate-error",
        kind="mechanical",
        forms=(
            "Translate these three user-facing error strings into French.",
            "I need the error messages below in French, same tone.",
            "Give me French versions of these three messages.",
        ),
    ),
    Family(
        name="sort-imports",
        kind="mechanical",
        forms=(
            "Sort the imports in this file into standard library, third party and "
            "local groups, alphabetise inside each group, and leave one blank line "
            "between the groups.",
            "Reorder these imports the way isort would.",
            "Group and alphabetise the import block below.",
        ),
    ),
    Family(
        name="checkout-timeout",
        kind="deliberative",
        forms=(
            "Our checkout service times out under load about once an hour and the "
            "logs show no errors. How should we work out what is going wrong?",
            "Once an hour checkout hangs and recovers by itself. Nothing in the "
            "logs. Where would you start looking?",
            "Intermittent checkout timeouts, roughly hourly, clean logs. What is "
            "the most likely cause and how would you confirm it?",
        ),
    ),
    Family(
        name="index-choice",
        kind="deliberative",
        forms=(
            "Index for tenant_id plus a created_at range, sorted by created_at?",
            "Which composite index suits a query that filters tenant_id plus a "
            "date range and orders by the date?",
            "We filter on tenant and a created_at window, then sort by "
            "created_at. What is the right index here?",
        ),
    ),
    Family(
        name="queue-or-cron",
        kind="deliberative",
        forms=(
            "Queue or cron for nightly invoices?",
            "Cron or a work queue for nightly invoices, given retries have to be "
            "per-invoice rather than per-run?",
            "We generate invoices nightly. Queue or scheduled job, and what does "
            "that decide about retries?",
        ),
    ),
    Family(
        name="migration-plan",
        kind="deliberative",
        forms=(
            "Plan a zero-downtime split of a 400M row table into two, with active writers.",
            "How would you split a very large table in two while writes continue?",
            "We need to move half the columns of a huge table into a new one "
            "without a maintenance window. What is the order of operations?",
        ),
    ),
    Family(
        name="auth-model",
        kind="deliberative",
        forms=(
            "Permissions on users or on groups?",
            "We are designing roles for an admin console. Per user or per group, "
            "and what does each choice cost us later?",
            "Users, groups or both for permissions in a small admin tool?",
        ),
    ),
    Family(
        name="flaky-test",
        kind="deliberative",
        forms=(
            "Passes alone, fails in the suite. Why?",
            "A test only fails when the whole suite runs. What are the usual "
            "causes and how would you narrow it down?",
            "Suite-only failure, passes in isolation. Where do I look first?",
        ),
    ),
    Family(
        name="cache-strategy",
        kind="deliberative",
        forms=(
            "What should we key a response cache on for an endpoint that takes a "
            "tenant, a filter set and a page number?",
            "Designing a cache key for a paged, filtered, tenant-scoped endpoint. "
            "What belongs in it and what does not?",
            "How do we cache this endpoint without serving one tenant another "
            "tenant's page?",
        ),
    ),
    Family(
        name="eventual-consistency",
        kind="deliberative",
        forms=(
            "Users see a stale count for a few seconds after they act. Is that "
            "worth fixing, and how would we decide?",
            "Our read model lags the write by a second or two. How do we work out "
            "whether that matters to anyone?",
            "How should we think about a couple of seconds of read lag in a "
            "counter people watch?",
        ),
    ),
    Family(
        name="retry-policy",
        kind="deliberative",
        forms=(
            "What retry policy for a payment capture?",
            "Designing retries for a payment API that may charge twice. What is "
            "safe here?",
            "What retry policy would you write for a call that moves money?",
        ),
    ),
    Family(
        name="add-retries",
        kind="deliberative",
        forms=(
            "Add retries to the payment client.",
            "Put retries around the capture call in the payment client, and pick "
            "the backoff and the stopping rule.",
            "The payment client has no retries. Add them, and decide what is safe "
            "to retry and what is not.",
        ),
    ),
    Family(
        name="email-validator",
        kind="deliberative",
        forms=(
            "Write an email validator for the signup form.",
            "We need an email validator that accepts what our signup form should "
            "accept and rejects the rest. Write it.",
            "Implement email validation for signup. Decide what counts as valid.",
        ),
    ),
    Family(
        name="write-tests",
        kind="deliberative",
        forms=(
            "What tests would you write for the refund path below, and which ones "
            "are worth the maintenance?",
            "Given this refund function, which cases actually need a test?",
            "Help me decide the test cases for a partial-refund path with retries.",
        ),
    ),
)

MESSAGES: tuple[str, ...] = tuple(form for family in FAMILIES for form in family.forms)

FAMILY_OF: dict[str, Family] = {
    form: family for family in FAMILIES for form in family.forms
}


def stream(name: str, count: int, seed: int = 7) -> list[str]:
    """`unique` sends every message once; `zipf` repeats a popular head."""
    if name == "unique":
        return list(MESSAGES)
    rng = random.Random(seed)
    weights = [1.0 / (rank**1.1) for rank in range(1, len(MESSAGES) + 1)]
    order = list(MESSAGES)
    rng.shuffle(order)
    return rng.choices(order, weights=weights, k=count)
