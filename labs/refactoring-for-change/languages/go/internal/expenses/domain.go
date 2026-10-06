// Copyright (c) 2026 Zenable, Inc.
package expenses

import (
	"errors"
	"regexp"
)

var identifier = regexp.MustCompile("^[a-z][a-z0-9-]{0,31}$")

type Principal struct {
	Tenant string
	Actor  string
	Role   string
}

type Expense struct {
	Tenant    string
	Account   string
	Cents     int
	Policy    string
	RequestID string
}

type Snapshot struct {
	Alpha  int
	Beta   int
	Events int
}

func Validate(principal Principal, expense Expense) error {
	for _, value := range []string{principal.Tenant, principal.Actor, expense.Tenant, expense.Account, expense.Policy, expense.RequestID} {
		if !identifier.MatchString(value) {
			return errors.New("invalid_input")
		}
	}
	if principal.Role != "approver" && principal.Role != "viewer" {
		return errors.New("invalid_input")
	}
	if expense.Cents <= 0 || expense.Cents > 1000000 {
		return errors.New("invalid_input")
	}
	return nil
}
