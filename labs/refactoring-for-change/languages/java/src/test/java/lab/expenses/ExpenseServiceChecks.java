// Copyright (c) 2026 Zenable, Inc.
package lab.expenses;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;

public final class ExpenseServiceChecks {
    public static void main(String[] args) throws Exception {
        invalidStrategyResultsPreserveState();
        concurrentRetriesPayOnce();
        replayDoesNotRecalculatePolicy();
        System.out.println("Policy result and concurrent retry checks passed.");
    }

    private static void replayDoesNotRecalculatePolicy() {
        AtomicInteger calls = new AtomicInteger();
        ExpenseService service = new ExpenseService(Map.of("standard", expense -> {
            if (calls.incrementAndGet() > 1) throw new Refused("policy_limit");
            return expense.cents;
        }));
        Principal principal = new Principal("alpha", "alice", "approver");
        Expense expense = new Expense("alpha", "shared", 1000, "standard", "r1");
        if (!service.submit(principal, expense).equals("accepted")) {
            throw new AssertionError("Initial submission was not accepted");
        }
        if (!service.submit(principal, expense).equals("replayed")) {
            throw new AssertionError("Completed submission was not replayed");
        }
        Snapshot state = service.snapshot();
        if (state.alpha != 9000 || state.beta != 20000 || state.events != 1) {
            throw new AssertionError("Replay changed state");
        }
    }

    private static void invalidStrategyResultsPreserveState() {
        for (int amount : new int[] {-1, 0, 1001}) {
            ExpenseService service = new ExpenseService(Map.of("invalid", expense -> amount));
            try {
                service.submit(new Principal("alpha", "alice", "approver"),
                    new Expense("alpha", "shared", 1000, "invalid", "r1"));
                throw new AssertionError("An invalid policy result was accepted");
            } catch (Refused error) {
                if (!"invalid_policy_result".equals(error.getMessage())) throw error;
            }
            Snapshot state = service.snapshot();
            if (state.alpha != 10000 || state.beta != 20000 || state.events != 0) {
                throw new AssertionError("A rejected policy result changed state");
            }
        }
    }

    private static void concurrentRetriesPayOnce() throws Exception {
        ExpenseService service = new ExpenseService(Map.of("standard", new StandardPolicy()));
        Principal principal = new Principal("alpha", "alice", "approver");
        Expense expense = new Expense("alpha", "shared", 1000, "standard", "r1");
        ExecutorService executor = Executors.newFixedThreadPool(8);
        try {
            List<Callable<String>> requests = new ArrayList<>();
            for (int index = 0; index < 32; index++) requests.add(() -> service.submit(principal, expense));
            int accepted = 0;
            int replayed = 0;
            for (Future<String> result : executor.invokeAll(requests)) {
                String status = result.get();
                if (status.equals("accepted")) accepted++;
                if (status.equals("replayed")) replayed++;
            }
            Snapshot state = service.snapshot();
            if (accepted != 1 || replayed != 31 || state.alpha != 9000 || state.beta != 20000 || state.events != 1) {
                throw new AssertionError("Concurrent retries changed the effect count");
            }
        } finally {
            executor.shutdownNow();
        }
    }
}
