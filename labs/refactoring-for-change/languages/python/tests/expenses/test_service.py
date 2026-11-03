# Copyright (c) 2026 Zenable, Inc.
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from expenses.domain import Expense, Principal, Refused
from expenses.policies import ExpensePolicy, StandardPolicy
from expenses.service import ExpenseService


@pytest.mark.unit
@pytest.mark.parametrize("payable", [-1, 0, 1001, True])
def test_invalid_strategy_results_cannot_change_state(payable: int | bool) -> None:
    policy = Mock(spec=ExpensePolicy)
    policy.reimburse.return_value = payable
    service = ExpenseService({"invalid": policy})
    principal = Principal(tenant="alpha", actor="alice", role="approver")
    expense = Expense(
        tenant="alpha", account="shared", cents=1000, policy="invalid", request_id="r1"
    )
    before = service.snapshot()
    with pytest.raises(Refused, match="invalid_policy_result"):
        service.submit(principal, expense)
    assert service.snapshot() == before


@pytest.mark.integration
def test_concurrent_retries_pay_once() -> None:
    service = ExpenseService({"standard": StandardPolicy()})
    principal = Principal(tenant="alpha", actor="alice", role="approver")
    expense = Expense(
        tenant="alpha", account="shared", cents=1000, policy="standard", request_id="r1"
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(lambda _: service.submit(principal, expense), range(32))
        )
    assert results.count("accepted") == 1
    assert results.count("replayed") == 31
    snapshot = service.snapshot()
    assert (snapshot.alpha, snapshot.beta, snapshot.events) == (9000, 20000, 1)


@pytest.mark.unit
def test_replay_uses_recorded_result_without_recalculating_policy() -> None:
    policy = Mock(spec=ExpensePolicy)
    policy.reimburse.side_effect = [1000, Refused("policy_limit")]
    service = ExpenseService({"standard": policy})
    principal = Principal(tenant="alpha", actor="alice", role="approver")
    expense = Expense(
        tenant="alpha", account="shared", cents=1000, policy="standard", request_id="r1"
    )
    assert service.submit(principal, expense) == "accepted"
    before = service.snapshot()
    assert service.submit(principal, expense) == "replayed"
    assert service.snapshot() == before
