// Copyright (c) 2026 Zenable, Inc.
package lab.expenses;

public final class Principal {
    public final String tenant;
    public final String actor;
    public final String role;

    public Principal(String tenant, String actor, String role) {
        Expense.requireIdentifier(tenant);
        Expense.requireIdentifier(actor);
        if (!"approver".equals(role) && !"viewer".equals(role)) {
            throw new IllegalArgumentException("invalid_input");
        }
        this.tenant = tenant;
        this.actor = actor;
        this.role = role;
    }
}
