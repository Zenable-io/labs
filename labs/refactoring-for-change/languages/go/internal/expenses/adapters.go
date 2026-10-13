// Copyright (c) 2026 Zenable, Inc.
package expenses

type Submitter interface {
	Submit(Principal, Expense) (string, error)
}

type WebExpenses struct{ Service Submitter }

func (web WebExpenses) Submit(principal Principal, expense Expense) (string, error) {
	return web.Service.Submit(principal, expense)
}

type BatchExpenses struct{ Service Submitter }

func (batch BatchExpenses) Submit(principal Principal, expense Expense) (string, error) {
	return batch.Service.Submit(principal, expense)
}
