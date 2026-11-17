# Copyright (c) 2026 Zenable, Inc.
from typing import Protocol

from expenses.domain import Expense, Refused


class ExpensePolicy(Protocol):
    def reimburse(self, expense: Expense) -> int: ...


class StandardPolicy:
    def reimburse(self, expense: Expense) -> int:
        if expense.cents > 5_000:
            raise Refused("policy_limit")
        return expense.cents


class TravelPolicy:
    def reimburse(self, expense: Expense) -> int:
        if expense.cents > 10_000:
            raise Refused("policy_limit")
        return expense.cents * 4 // 5
