// Copyright (c) 2026 Zenable, Inc.
package lab.expenses;

public final class TravelPolicy implements ExpensePolicy {
    @Override
    public int reimburse(Expense expense) {
        if (expense.cents > 10_000) throw new Refused("policy_limit");
        return expense.cents * 4 / 5;
    }
}
