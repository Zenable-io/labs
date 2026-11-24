# Copyright (c) 2026 Zenable, Inc.
from expenses.domain import Expense, Principal, Refused, Snapshot


class HistoricalExpenses:
    """Deliberately unsafe historical example, used only with synthetic accounts."""

    def __init__(self) -> None:
        self.accounts = {("alpha", "shared"): 10_000, ("beta", "shared"): 20_000}
        self.events: list[Expense] = []

    def web(self, principal: Principal, expense: Expense) -> str:
        if principal.role != "approver" or principal.tenant != expense.tenant:
            raise Refused("forbidden")
        payable = expense.cents
        if expense.policy == "standard":
            if expense.cents > 5_000:
                raise Refused("policy_limit")
        elif expense.policy == "travel":
            if expense.cents > 10_000:
                raise Refused("policy_limit")
            payable = expense.cents * 4 // 5
        else:
            raise Refused("unknown_policy")
        key = (expense.tenant, expense.account)
        if key not in self.accounts:
            raise Refused("not_found")
        if payable > self.accounts[key]:
            raise Refused("insufficient_budget")
        self.accounts[key] -= payable
        self.events.append(expense)
        return "accepted"

    def batch(self, principal: Principal, expense: Expense) -> str:
        key = (expense.tenant, expense.account)
        if key not in self.accounts:
            raise Refused("not_found")
        self.accounts[key] -= expense.cents
        return "accepted"

    def snapshot(self) -> Snapshot:
        return Snapshot(
            alpha=self.accounts[("alpha", "shared")],
            beta=self.accounts[("beta", "shared")],
            events=len(self.events),
        )
