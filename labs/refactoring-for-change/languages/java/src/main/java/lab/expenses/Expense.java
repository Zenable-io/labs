// Copyright (c) 2026 Zenable, Inc.
package lab.expenses;

import java.util.Objects;
import java.util.regex.Pattern;

public final class Expense {
    private static final Pattern IDENTIFIER = Pattern.compile("^[a-z][a-z0-9-]{0,31}$");
    public final String tenant;
    public final String account;
    public final int cents;
    public final String policy;
    public final String requestId;

    public Expense(String tenant, String account, int cents, String policy, String requestId) {
        requireIdentifier(tenant);
        requireIdentifier(account);
        requireIdentifier(policy);
        requireIdentifier(requestId);
        if (cents <= 0 || cents > 1_000_000) {
            throw new IllegalArgumentException("invalid_input");
        }
        this.tenant = tenant;
        this.account = account;
        this.cents = cents;
        this.policy = policy;
        this.requestId = requestId;
    }

    static void requireIdentifier(String value) {
        if (value == null || !IDENTIFIER.matcher(value).matches()) {
            throw new IllegalArgumentException("invalid_input");
        }
    }

    @Override
    public boolean equals(Object other) {
        if (!(other instanceof Expense)) return false;
        Expense expense = (Expense) other;
        return tenant.equals(expense.tenant) && account.equals(expense.account)
            && cents == expense.cents && policy.equals(expense.policy)
            && requestId.equals(expense.requestId);
    }

    @Override
    public int hashCode() {
        return Objects.hash(tenant, account, cents, policy, requestId);
    }
}
