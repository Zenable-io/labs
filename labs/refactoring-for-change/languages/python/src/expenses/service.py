# Copyright (c) 2026 Zenable, Inc.
from collections.abc import Mapping
from threading import Lock

from pydantic import BaseModel, ConfigDict

from expenses.domain import Expense, Principal, Receipt, Refused, Snapshot
from expenses.policies import ExpensePolicy


class AccountState(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    remaining: int
    receipts: tuple[Receipt, ...] = ()


class ExpenseService:
    def __init__(self, policies: Mapping[str, ExpensePolicy]) -> None:
        self._policies = dict(policies)
        self._accounts = {
            ("alpha", "shared"): AccountState(remaining=10_000),
            ("beta", "shared"): AccountState(remaining=20_000),
        }
        self._lock = Lock()

    def submit(self, principal: Principal, expense: Expense) -> str:
        if principal.role != "approver" or principal.tenant != expense.tenant:
            raise Refused("forbidden")
        with self._lock:
            for state_key, state in self._accounts.items():
                if state_key[0] != principal.tenant:
                    continue
                for receipt in state.receipts:
                    if receipt.expense.request_id != expense.request_id:
                        continue
                    if receipt.actor != principal.actor or receipt.expense != expense:
                        raise Refused("idempotency_conflict")
                    return "replayed"
            policy = self._policies.get(expense.policy)
            if policy is None:
                raise Refused("unknown_policy")
            payable = policy.reimburse(expense)
            if type(payable) is not int or not 0 < payable <= expense.cents:
                raise Refused("invalid_policy_result")
            key = (principal.tenant, expense.account)
            account = self._accounts.get(key)
            if account is None:
                raise Refused("not_found")
            if payable > account.remaining:
                raise Refused("insufficient_budget")
            receipt = Receipt(
                tenant=principal.tenant,
                actor=principal.actor,
                expense=expense,
                paid_cents=payable,
            )
            # Publish the debit and its audit record together; readers never see half a submission.
            self._accounts[key] = AccountState(
                remaining=account.remaining - payable,
                receipts=(*account.receipts, receipt),
            )
            return "accepted"

    def snapshot(self) -> Snapshot:
        with self._lock:
            return Snapshot(
                alpha=self._accounts[("alpha", "shared")].remaining,
                beta=self._accounts[("beta", "shared")].remaining,
                events=sum(len(state.receipts) for state in self._accounts.values()),
            )
