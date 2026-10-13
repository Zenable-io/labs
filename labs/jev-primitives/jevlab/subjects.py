"""Copyright (c) 2026 Zenable, Inc. The corpus every exercise judges: one changed file, six requirements, five
guardrail engines, and one proposed requirement to grade.

Small on purpose. Accuracy falls as the state grows with detail the decision
does not need, so each question gets the file, the patch and the requirement,
and nothing else the repository happens to contain.
"""

from pydantic import BaseModel, ConfigDict


class Requirement(BaseModel):
    """A written rule the repository holds itself to."""

    model_config = ConfigDict(frozen=True, strict=True)

    name: str
    statement: str
    rationale: str


class Engine(BaseModel):
    """A guardrail tool, and what kind of check it can express."""

    model_config = ConfigDict(frozen=True, strict=True)

    name: str
    capabilities: str


FILE_PATH = "src/billing/refunds.py"

FILE_CONTENT = '''"""Refunds against a completed charge."""

import logging

from billing.gateway import Gateway
from billing.store import Store

log = logging.getLogger(__name__)


def eligible(charge: dict) -> bool:
    return charge["state"] == "captured" and not charge.get("disputed")


def refund(charge_id: str, amount: float, gateway: Gateway, store: Store) -> dict:
    charge = store.load_charge(charge_id)
    if not eligible(charge):
        raise ValueError("charge is not refundable")
    log.info("refunding %s for %s", charge_id, amount)
    receipt = gateway.refund(charge_id, amount)
    store.save_receipt(charge_id, receipt)
    return receipt
'''

FILE_PATCH = """@@ -11,9 +11,17 @@ def eligible(charge: dict) -> bool:
     return charge["state"] == "captured" and not charge.get("disputed")


-def refund(charge_id: str, amount: float, gateway: Gateway, store: Store) -> dict:
+def refund(charge_id: str, amount: float, gateway: Gateway, store: Store) -> dict:
     charge = store.load_charge(charge_id)
     if not eligible(charge):
         raise ValueError("charge is not refundable")
-    log.info("refunding %s for %s", charge_id, amount)
+    remaining = charge["total"] - charge.get("refunded", 0.0)
+    if amount > remaining:
+        amount = remaining
+    log.info("refunding %s for %s", charge_id, amount)
     receipt = gateway.refund(charge_id, amount)
+    for attempt in range(3):
+        if receipt.get("status") == "pending":
+            receipt = gateway.refund(charge_id, amount)
     store.save_receipt(charge_id, receipt)
     return receipt
"""

REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        name="money-as-minor-units",
        statement=(
            "Monetary amounts are carried as integer minor units or as Decimal. "
            "A float never holds an amount of money."
        ),
        rationale="Binary floating point cannot represent most decimal amounts exactly.",
    ),
    Requirement(
        name="retries-carry-idempotency",
        statement=(
            "Any request that the code may send more than once carries an "
            "idempotency key chosen by the caller and reused across the retries."
        ),
        rationale="A retried payment call without a key can move money twice.",
    ),
    Requirement(
        name="structured-logs",
        statement=(
            "Log records are emitted as structured fields, and every record "
            "carries the request identifier it belongs to."
        ),
        rationale="Printf-style records cannot be filtered or joined after the fact.",
    ),
    Requirement(
        name="jsonb-not-json",
        statement=(
            "A dictionary or JSON document stored in PostgreSQL uses a JSONB "
            "column. The JSON column type is never used."
        ),
        rationale="JSON stores the source text and cannot be indexed by key.",
    ),
    Requirement(
        name="docs-links-carry-utm",
        statement=(
            "A link to the documentation site carries UTM parameters naming the "
            "surface the reader clicked from."
        ),
        rationale="Untagged links make it impossible to tell which surface sends readers.",
    ),
    Requirement(
        name="no-literal-credentials",
        statement=(
            "Credentials, API keys and tokens are read from configuration. None "
            "of them appears as a literal in source."
        ),
        rationale="A literal in source outlives every rotation and every revocation.",
    ),
)

ENGINES: tuple[Engine, ...] = (
    Engine(
        name="semgrep",
        capabilities=(
            "Matches syntactic patterns and simple intra-file dataflow in source "
            "code across many languages. Sees one file at a time and cannot "
            "resolve a call into another module."
        ),
    ),
    Engine(
        name="eslint",
        capabilities=(
            "Walks the JavaScript and TypeScript abstract syntax tree with one "
            "rule per check. Sees no other language and no file outside the "
            "project's source."
        ),
    ),
    Engine(
        name="checkov",
        capabilities=(
            "Reads infrastructure-as-code resources and their attributes in "
            "Terraform, CloudFormation and Kubernetes manifests. Sees no "
            "application source."
        ),
    ),
    Engine(
        name="sqlfluff",
        capabilities=(
            "Parses SQL statements and lints their syntax, layout and dialect "
            "usage. Sees SQL files and SQL embedded where it is configured to "
            "look, and nothing else."
        ),
    ),
    Engine(
        name="gitleaks",
        capabilities=(
            "Scans text for strings shaped like secrets, using entropy and a "
            "catalogue of known credential formats. Reads any file as text and "
            "parses no language."
        ),
    ),
)

CANDIDATE_REQUIREMENT = (
    "Code should be clean and handle errors properly, and developers should "
    "make sure that money is dealt with carefully."
)


def file_state() -> dict[str, object]:
    """The changed file, as every Noul question sees it."""
    return {"path": FILE_PATH, "content": FILE_CONTENT, "patch": FILE_PATCH}
