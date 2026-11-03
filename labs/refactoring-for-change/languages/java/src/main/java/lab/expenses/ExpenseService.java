// Copyright (c) 2026 Zenable, Inc.
package lab.expenses;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

public final class ExpenseService {
    private static final class AccountKey {
        final String tenant;
        final String account;

        AccountKey(String tenant, String account) {
            this.tenant = tenant;
            this.account = account;
        }

        @Override
        public boolean equals(Object other) {
            if (!(other instanceof AccountKey)) return false;
            AccountKey key = (AccountKey) other;
            return tenant.equals(key.tenant) && account.equals(key.account);
        }

        @Override
        public int hashCode() {
            return Objects.hash(tenant, account);
        }
    }

    private static final class Receipt {
        final String actor;
        final Expense expense;
        final int paidCents;

        Receipt(String actor, Expense expense, int paidCents) {
            this.actor = actor;
            this.expense = expense;
            this.paidCents = paidCents;
        }
    }

    private static final class AccountState {
        final int remaining;
        final List<Receipt> receipts;

        AccountState(int remaining, List<Receipt> receipts) {
            this.remaining = remaining;
            this.receipts = List.copyOf(receipts);
        }
    }

    private final Map<String, ExpensePolicy> policies;
    private final Map<AccountKey, AccountState> accounts = new HashMap<>();

    public ExpenseService(Map<String, ExpensePolicy> policies) {
        this.policies = Map.copyOf(policies);
        accounts.put(new AccountKey("alpha", "shared"), new AccountState(10_000, List.of()));
        accounts.put(new AccountKey("beta", "shared"), new AccountState(20_000, List.of()));
    }

    public synchronized String submit(Principal principal, Expense expense) {
        if (!principal.role.equals("approver") || !principal.tenant.equals(expense.tenant)) {
            throw new Refused("forbidden");
        }
        for (Map.Entry<AccountKey, AccountState> entry : accounts.entrySet()) {
            if (!entry.getKey().tenant.equals(principal.tenant)) continue;
            for (Receipt previous : entry.getValue().receipts) {
                if (!previous.expense.requestId.equals(expense.requestId)) continue;
                if (!previous.actor.equals(principal.actor) || !previous.expense.equals(expense)) {
                    throw new Refused("idempotency_conflict");
                }
                return "replayed";
            }
        }
        ExpensePolicy policy = policies.get(expense.policy);
        if (policy == null) throw new Refused("unknown_policy");
        int payable = policy.reimburse(expense);
        if (payable <= 0 || payable > expense.cents) throw new Refused("invalid_policy_result");
        AccountKey key = new AccountKey(principal.tenant, expense.account);
        AccountState account = accounts.get(key);
        if (account == null) throw new Refused("not_found");
        if (payable > account.remaining) throw new Refused("insufficient_budget");
        List<Receipt> receipts = new ArrayList<>(account.receipts);
        receipts.add(new Receipt(principal.actor, expense, payable));
        // Publish the debit and its audit record together.
        accounts.put(key, new AccountState(account.remaining - payable, receipts));
        return "accepted";
    }

    public synchronized Snapshot snapshot() {
        int events = accounts.values().stream().mapToInt(account -> account.receipts.size()).sum();
        return new Snapshot(accounts.get(new AccountKey("alpha", "shared")).remaining,
                            accounts.get(new AccountKey("beta", "shared")).remaining, events);
    }
}
