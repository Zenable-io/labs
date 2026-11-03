"""Copyright (c) 2026 Zenable, Inc. A second slice of traffic, and a house rule the written criteria do not carry.

The corpus in `corpus.py` separates cleanly: the criteria were written for it,
and Jev puts every one of its sixty-six requests where the label says. That is
what a policy looks like when the only judgement involved is the one already
written down.

These twelve families are the argument. Every one of them touches money, and
about half of them are mechanical by any reading of the criteria: renaming a
field, converting a price list, adding type hints. A team that has had one bad
refund migration decides that anything touching money goes to the larger model
whatever it looks like, and nothing in the criteria says so, because the
criteria are about the reasoning a request needs rather than what it costs to
get wrong.

So the disagreement here is not a mistake Jev made. It is a policy this rig has
not been told about, and telling it is what `jeva` is for.
"""

from pydantic import BaseModel, ConfigDict


class HouseFamily(BaseModel):
    """One unit of money-touching work, and two ways a person asks for it."""

    model_config = ConfigDict(frozen=True, strict=True)

    name: str

    reads_as: str
    """`mechanical` or `deliberative`, by the criteria as written."""

    forms: tuple[str, str]


HOUSE_FAMILIES: tuple[HouseFamily, ...] = (
    HouseFamily(
        name="rename-charge-field",
        reads_as="mechanical",
        forms=(
            "Rename `chargeAmount` to `amount_cents` across billing/ and update the callers.",
            "In billing/, `chargeAmount` should be `amount_cents` everywhere it appears.",
        ),
    ),
    HouseFamily(
        name="price-list-format",
        reads_as="mechanical",
        forms=(
            "Convert this price list from JSON to YAML, keeping the key order.",
            "Turn the attached tariff JSON into equivalent YAML.",
        ),
    ),
    HouseFamily(
        name="refund-type-hints",
        reads_as="mechanical",
        forms=(
            "Add type hints to every function in billing/refunds.py, including return types.",
            "billing/refunds.py has no annotations. Add them.",
        ),
    ),
    HouseFamily(
        name="invoice-csv-header",
        reads_as="mechanical",
        forms=(
            "What are the column names in the first line of this invoice export?",
            "Read the header row off this settlement CSV and list the fields.",
        ),
    ),
    HouseFamily(
        name="currency-strings",
        reads_as="mechanical",
        forms=(
            "Translate these four payment failure messages into German.",
            "I need the payment error strings below in German, same tone.",
        ),
    ),
    HouseFamily(
        name="ledger-docstring",
        reads_as="mechanical",
        forms=(
            "Write a docstring for the ledger posting function below, arguments and return value.",
            "This ledger function has no docstring. Write one from what it does.",
        ),
    ),
    HouseFamily(
        name="capture-retries",
        reads_as="deliberative",
        forms=(
            "What retry policy would you write for a payment capture that may charge twice?",
            "Designing retries for a call that moves money. What is safe here?",
        ),
    ),
    HouseFamily(
        name="refund-split",
        reads_as="deliberative",
        forms=(
            "Plan a zero-downtime split of the refunds table, with active writers.",
            "How would you split the refunds table in two while writes continue?",
        ),
    ),
    HouseFamily(
        name="rounding-rule",
        reads_as="deliberative",
        forms=(
            "We round tax per line and the invoice total is a cent out. How should we decide where to round?",
            "Per-line rounding leaves our totals a cent off. Where does the rounding belong?",
        ),
    ),
    HouseFamily(
        name="chargeback-webhook",
        reads_as="deliberative",
        forms=(
            "Chargeback webhooks arrive twice and sometimes out of order. How do we make the handler safe?",
            "Our chargeback webhook is not idempotent. What is the right shape for it?",
        ),
    ),
    HouseFamily(
        name="payout-batch-size",
        reads_as="deliberative",
        forms=(
            "Payouts run nightly in one batch and a single failure holds the rest. Batch or per-payout?",
            "One failed payout stalls the nightly run. How should we break the batch up?",
        ),
    ),
    HouseFamily(
        name="fx-cache",
        reads_as="deliberative",
        forms=(
            "How long may we cache an FX rate before a quote we show is a price we cannot honour?",
            "We cache FX rates for quotes. What decides the TTL here?",
        ),
    ),
)

HOUSE_MESSAGES: tuple[str, ...] = tuple(
    form for family in HOUSE_FAMILIES for form in family.forms
)

HOUSE_FAMILY_OF: dict[str, HouseFamily] = {
    form: family for family in HOUSE_FAMILIES for form in family.forms
}

HOUSE_RULE = (
    "Anything touching money goes to the larger model, however mechanical it looks."
)
"""The rule in one sentence. It is not in `policy.json`, which is why half of
this traffic goes somewhere the team does not want it to."""
