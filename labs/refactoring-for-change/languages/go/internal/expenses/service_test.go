// Copyright (c) 2026 Zenable, Inc.
package expenses

import (
	"errors"
	"sync"
	"testing"
)

type changingPolicy struct { calls int }

func (policy *changingPolicy) Reimburse(expense Expense) (int, error) {
	policy.calls++
	if policy.calls > 1 { return 0, errors.New("policy_limit") }
	return expense.Cents, nil
}

func TestReplayDoesNotRecalculatePolicy(t *testing.T) {
	service := NewService(map[string]ExpensePolicy{"standard": &changingPolicy{}})
	principal := Principal{Tenant: "alpha", Actor: "alice", Role: "approver"}
	expense := Expense{Tenant: "alpha", Account: "shared", Cents: 1000, Policy: "standard", RequestID: "r1"}
	if result, err := service.Submit(principal, expense); err != nil || result != "accepted" {
		t.Fatalf("expected accepted, got %q, %v", result, err)
	}
	before := service.Snapshot()
	if result, err := service.Submit(principal, expense); err != nil || result != "replayed" {
		t.Fatalf("expected replayed, got %q, %v", result, err)
	}
	if after := service.Snapshot(); after != before { t.Fatalf("replay changed state: %+v", after) }
}

type invalidPolicy struct { amount int }

func (policy invalidPolicy) Reimburse(Expense) (int, error) {
	return policy.amount, nil
}

func TestInvalidStrategyResultsPreserveState(t *testing.T) {
	for _, amount := range []int{-1, 0, 1001} {
		service := NewService(map[string]ExpensePolicy{"invalid": invalidPolicy{amount}})
		principal := Principal{Tenant: "alpha", Actor: "alice", Role: "approver"}
		expense := Expense{Tenant: "alpha", Account: "shared", Cents: 1000, Policy: "invalid", RequestID: "r1"}
		before := service.Snapshot()
		if _, err := service.Submit(principal, expense); err == nil || err.Error() != "invalid_policy_result" {
			t.Fatalf("amount %d: expected invalid_policy_result, got %v", amount, err)
		}
		if after := service.Snapshot(); after != before {
			t.Fatalf("amount %d changed state: %+v", amount, after)
		}
	}
}

func TestConcurrentRetriesPayOnce(t *testing.T) {
	service := NewService(map[string]ExpensePolicy{"standard": StandardPolicy{}})
	principal := Principal{Tenant: "alpha", Actor: "alice", Role: "approver"}
	expense := Expense{Tenant: "alpha", Account: "shared", Cents: 1000, Policy: "standard", RequestID: "r1"}
	results := make(chan string, 32)
	var workers sync.WaitGroup
	for range 32 {
		workers.Add(1)
		go func() {
			defer workers.Done()
			result, err := service.Submit(principal, expense)
			if err != nil { results <- err.Error(); return }
			results <- result
		}()
	}
	workers.Wait()
	close(results)
	counts := map[string]int{}
	for result := range results { counts[result]++ }
	if counts["accepted"] != 1 || counts["replayed"] != 31 {
		t.Fatalf("unexpected results: %+v", counts)
	}
	if state := service.Snapshot(); state != (Snapshot{Alpha: 9000, Beta: 20000, Events: 1}) {
		t.Fatalf("unexpected state: %+v", state)
	}
}
