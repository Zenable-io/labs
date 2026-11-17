// Copyright (c) 2026 Zenable, Inc.
package lab.expenses;

public final class BatchExpenses {
    private final ExpenseService service;

    public BatchExpenses(ExpenseService service) {
        this.service = service;
    }

    public String submit(Principal principal, Expense expense) {
        return service.submit(principal, expense);
    }
}
