// Copyright (c) 2026 Zenable, Inc.
package expenses

import "errors"

type ExpensePolicy interface {
	Reimburse(Expense) (int, error)
}

type StandardPolicy struct{}

func (StandardPolicy) Reimburse(expense Expense) (int, error) {
	if expense.Cents > 5000 {
		return 0, errors.New("policy_limit")
	}
	return expense.Cents, nil
}

type TravelPolicy struct{}

func (TravelPolicy) Reimburse(expense Expense) (int, error) {
	if expense.Cents > 10000 {
		return 0, errors.New("policy_limit")
	}
	return expense.Cents * 4 / 5, nil
}
