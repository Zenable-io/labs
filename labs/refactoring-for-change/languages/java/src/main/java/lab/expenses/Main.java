// Copyright (c) 2026 Zenable, Inc.
package lab.expenses;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Map;

public final class Main {
    public static void main(String[] args) throws IOException {
        if (args.length != 1 || (!args[0].equals("history") && !args[0].equals("design"))) {
            System.err.println("Usage: expenses history|design");
            System.exit(2);
        }
        ExpenseService service = new ExpenseService(Map.of(
            "standard", new StandardPolicy(), "travel", new TravelPolicy()));
        HistoricalExpenses history = new HistoricalExpenses();
        WebExpenses web = new WebExpenses(service);
        BatchExpenses batch = new BatchExpenses(service);
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank() || line.startsWith("#")) continue;
                String result = process(line, args[0], history, web, batch);
                Snapshot state = args[0].equals("history") ? history.snapshot() : service.snapshot();
                System.out.printf("%s\t%d\t%d\t%d%n", result, state.alpha, state.beta, state.events);
            }
        }
    }

    private static String process(String line, String mode, HistoricalExpenses history,
                                  WebExpenses web, BatchExpenses batch) {
        try {
            String[] fields = line.split("\t", -1);
            if (fields.length != 9 || (!fields[0].equals("web") && !fields[0].equals("batch"))) {
                return "invalid_input";
            }
            Principal principal = new Principal(fields[1], fields[2], fields[3]);
            Expense expense = new Expense(fields[4], fields[5], Integer.parseInt(fields[6]),
                                          fields[7], fields[8]);
            if (mode.equals("history")) {
                return fields[0].equals("web") ? history.web(principal, expense)
                                               : history.batch(principal, expense);
            }
            return fields[0].equals("web") ? web.submit(principal, expense)
                                           : batch.submit(principal, expense);
        } catch (Refused error) {
            return error.getMessage();
        } catch (IllegalArgumentException error) {
            return "invalid_input";
        }
    }
}
