// Copyright (c) 2026 Zenable, Inc.
package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"

	"example.com/expense-lab/internal/expenses"
)

func main() {
	if len(os.Args) != 2 || (os.Args[1] != "history" && os.Args[1] != "design") {
		fmt.Fprintln(os.Stderr, "Usage: expenses history|design")
		os.Exit(2)
	}
	service := expenses.NewService(map[string]expenses.ExpensePolicy{
		"standard": expenses.StandardPolicy{}, "travel": expenses.TravelPolicy{},
	})
	history := expenses.NewHistory()
	routes := map[string]expenses.Submitter{
		"web": expenses.WebExpenses{Service: service},
		"batch": expenses.BatchExpenses{Service: service},
	}
	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.TrimSpace(line) == "" || strings.HasPrefix(line, "#") {
			continue
		}
		result := process(line, os.Args[1], routes, history)
		state := service.Snapshot()
		if os.Args[1] == "history" {
			state = history.Snapshot()
		}
		fmt.Printf("%s\t%d\t%d\t%d\n", result, state.Alpha, state.Beta, state.Events)
	}
	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func process(line, mode string, routes map[string]expenses.Submitter, history *expenses.HistoricalExpenses) string {
	fields := strings.Split(line, "\t")
	if len(fields) != 9 {
		return "invalid_input"
	}
	route, found := routes[fields[0]]
	amount, err := strconv.Atoi(fields[6])
	if !found || err != nil {
		return "invalid_input"
	}
	principal := expenses.Principal{Tenant: fields[1], Actor: fields[2], Role: fields[3]}
	expense := expenses.Expense{Tenant: fields[4], Account: fields[5], Cents: amount, Policy: fields[7], RequestID: fields[8]}
	if err = expenses.Validate(principal, expense); err != nil {
		return "invalid_input"
	}
	var result string
	if mode == "history" {
		if fields[0] == "web" {
			result, err = history.Web(principal, expense)
		} else {
			result, err = history.Batch(principal, expense)
		}
	} else {
		result, err = route.Submit(principal, expense)
	}
	if err != nil {
		return err.Error()
	}
	return result
}
