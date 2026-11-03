// Copyright (c) 2026 Zenable, Inc.
package expenses

import (
	"errors"
	"maps"
	"sync"
)

type accountKey struct {
	tenant  string
	account string
}

type receipt struct {
	actor   string
	expense Expense
	paidCents int
}

type accountState struct {
	remaining int
	receipts  []receipt
}

type ExpenseService struct {
	mu       sync.Mutex
	policies map[string]ExpensePolicy
	accounts map[accountKey]accountState
}

func NewService(policies map[string]ExpensePolicy) *ExpenseService {
	return &ExpenseService{
		policies: maps.Clone(policies),
		accounts: map[accountKey]accountState{
			{"alpha", "shared"}: {remaining: 10000},
			{"beta", "shared"}:  {remaining: 20000},
		},
	}
}

func (service *ExpenseService) Submit(principal Principal, expense Expense) (string, error) {
	if err := Validate(principal, expense); err != nil {
		return "", err
	}
	if principal.Role != "approver" || principal.Tenant != expense.Tenant {
		return "", errors.New("forbidden")
	}
	service.mu.Lock()
	defer service.mu.Unlock()
	for stateKey, state := range service.accounts {
		if stateKey.tenant != principal.Tenant {
			continue
		}
		for _, previous := range state.receipts {
			if previous.expense.RequestID != expense.RequestID {
				continue
			}
			if previous.actor != principal.Actor || previous.expense != expense {
				return "", errors.New("idempotency_conflict")
			}
			return "replayed", nil
		}
	}
	policy, found := service.policies[expense.Policy]
	if !found || policy == nil {
		return "", errors.New("unknown_policy")
	}
	payable, err := policy.Reimburse(expense)
	if err != nil {
		return "", err
	}
	if payable <= 0 || payable > expense.Cents {
		return "", errors.New("invalid_policy_result")
	}
	key := accountKey{principal.Tenant, expense.Account}
	account, found := service.accounts[key]
	if !found {
		return "", errors.New("not_found")
	}
	if payable > account.remaining {
		return "", errors.New("insufficient_budget")
	}
	receipts := append(append([]receipt{}, account.receipts...), receipt{principal.Actor, expense, payable})
	// Publish the debit and its audit record together.
	service.accounts[key] = accountState{account.remaining - payable, receipts}
	return "accepted", nil
}

func (service *ExpenseService) Snapshot() Snapshot {
	service.mu.Lock()
	defer service.mu.Unlock()
	state := Snapshot{
		Alpha: service.accounts[accountKey{"alpha", "shared"}].remaining,
		Beta:  service.accounts[accountKey{"beta", "shared"}].remaining,
	}
	for _, account := range service.accounts {
		state.Events += len(account.receipts)
	}
	return state
}
