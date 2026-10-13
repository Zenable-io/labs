// Copyright (c) 2026 Zenable, Inc.
package expenses

import "errors"

// HistoricalExpenses is deliberately unsafe and only uses synthetic accounts.
type HistoricalExpenses struct {
	accounts map[accountKey]int
	events   []Expense
}

func NewHistory() *HistoricalExpenses {
	return &HistoricalExpenses{accounts: map[accountKey]int{
		{"alpha", "shared"}: 10000, {"beta", "shared"}: 20000,
	}}
}

func (history *HistoricalExpenses) Web(principal Principal, expense Expense) (string, error) {
	if principal.Role != "approver" || principal.Tenant != expense.Tenant {
		return "", errors.New("forbidden")
	}
	payable := expense.Cents
	if expense.Policy == "standard" {
		if expense.Cents > 5000 {
			return "", errors.New("policy_limit")
		}
	} else if expense.Policy == "travel" {
		if expense.Cents > 10000 {
			return "", errors.New("policy_limit")
		}
		payable = expense.Cents * 4 / 5
	} else {
		return "", errors.New("unknown_policy")
	}
	key := accountKey{expense.Tenant, expense.Account}
	balance, found := history.accounts[key]
	if !found {
		return "", errors.New("not_found")
	}
	if payable > balance {
		return "", errors.New("insufficient_budget")
	}
	history.accounts[key] -= payable
	history.events = append(history.events, expense)
	return "accepted", nil
}

func (history *HistoricalExpenses) Batch(principal Principal, expense Expense) (string, error) {
	key := accountKey{expense.Tenant, expense.Account}
	if _, found := history.accounts[key]; !found {
		return "", errors.New("not_found")
	}
	history.accounts[key] -= expense.Cents
	return "accepted", nil
}

func (history *HistoricalExpenses) Snapshot() Snapshot {
	return Snapshot{history.accounts[accountKey{"alpha", "shared"}],
		history.accounts[accountKey{"beta", "shared"}], len(history.events)}
}
