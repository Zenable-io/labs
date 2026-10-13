// Copyright (c) 2026 Zenable, Inc.
package lab.expenses;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Deliberately unsafe historical example, restricted to synthetic accounts. */
public final class HistoricalExpenses {
    private final Map<String, Integer> accounts = new HashMap<>();
    private final List<Expense> events = new ArrayList<>();

    public HistoricalExpenses() {
        accounts.put("alpha/shared", 10_000);
        accounts.put("beta/shared", 20_000);
    }

    public String web(Principal principal, Expense expense) {
        if (!principal.role.equals("approver") || !principal.tenant.equals(expense.tenant)) {
            throw new Refused("forbidden");
        }
        int payable = expense.cents;
        if (expense.policy.equals("standard")) {
            if (expense.cents > 5_000) throw new Refused("policy_limit");
        } else if (expense.policy.equals("travel")) {
            if (expense.cents > 10_000) throw new Refused("policy_limit");
            payable = expense.cents * 4 / 5;
        } else {
            throw new Refused("unknown_policy");
        }
        String key = expense.tenant + "/" + expense.account;
        Integer balance = accounts.get(key);
        if (balance == null) throw new Refused("not_found");
        if (payable > balance) throw new Refused("insufficient_budget");
        accounts.put(key, balance - payable);
        events.add(expense);
        return "accepted";
    }

    public String batch(Principal principal, Expense expense) {
        String key = expense.tenant + "/" + expense.account;
        Integer balance = accounts.get(key);
        if (balance == null) throw new Refused("not_found");
        accounts.put(key, balance - expense.cents);
        return "accepted";
    }

    public Snapshot snapshot() {
        return new Snapshot(accounts.get("alpha/shared"), accounts.get("beta/shared"), events.size());
    }
}
