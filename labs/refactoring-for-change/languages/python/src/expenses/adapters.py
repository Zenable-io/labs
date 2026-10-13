# Copyright (c) 2026 Zenable, Inc.
from expenses.domain import Expense, Principal
from expenses.service import ExpenseService


class WebExpenses:
    def __init__(self, service: ExpenseService) -> None:
        self._service = service

    def submit(self, principal: Principal, expense: Expense) -> str:
        return self._service.submit(principal, expense)


class BatchExpenses:
    def __init__(self, service: ExpenseService) -> None:
        self._service = service

    def submit(self, principal: Principal, expense: Expense) -> str:
        return self._service.submit(principal, expense)
