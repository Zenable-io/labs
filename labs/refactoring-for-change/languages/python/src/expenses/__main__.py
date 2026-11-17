# Copyright (c) 2026 Zenable, Inc.
import sys

from pydantic import ValidationError

from expenses.adapters import BatchExpenses, WebExpenses
from expenses.domain import Expense, Principal, Refused
from expenses.history import HistoricalExpenses
from expenses.policies import StandardPolicy, TravelPolicy
from expenses.service import ExpenseService


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("history", "design"):
        raise SystemExit("Usage: python -m expenses history|design")
    history = HistoricalExpenses()
    service = ExpenseService({"standard": StandardPolicy(), "travel": TravelPolicy()})
    routes = {"web": WebExpenses(service), "batch": BatchExpenses(service)}
    for line in sys.stdin:
        if not line.strip() or line.startswith("#"):
            continue
        try:
            (
                channel,
                tenant,
                actor,
                role,
                requested_tenant,
                account,
                cents,
                policy,
                request_id,
            ) = line.rstrip("\n").split("\t")
            if channel not in routes:
                raise ValueError("unknown channel")
            principal = Principal(tenant=tenant, actor=actor, role=role)
            expense = Expense(
                tenant=requested_tenant,
                account=account,
                cents=int(cents),
                policy=policy,
                request_id=request_id,
            )
            if sys.argv[1] == "history":
                result = getattr(history, channel)(principal, expense)
            else:
                result = routes[channel].submit(principal, expense)
        except Refused as error:
            result = str(error)
        except (ValueError, ValidationError):
            result = "invalid_input"
        state = history.snapshot() if sys.argv[1] == "history" else service.snapshot()
        print(f"{result}\t{state.alpha}\t{state.beta}\t{state.events}")


if __name__ == "__main__":
    main()
